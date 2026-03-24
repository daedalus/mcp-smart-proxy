from __future__ import annotations

from typing import Any

import structlog
from mcp.server import Server

from mcp_smart_proxy.config import Config
from mcp_smart_proxy.index.indexer import ToolIndexer
from mcp_smart_proxy.models import (
    IndexNotReadyError,
    ListResult,
    SearchResult,
    SearchResultItem,
    ServerInfo,
)
from mcp_smart_proxy.router import ToolRouter
from mcp_smart_proxy.upstream.manager import UpstreamManager

logger = structlog.get_logger(__name__)


class MCPSmartProxyServer:
    def __init__(self, config: Config):
        self._config = config
        self._upstream_manager = UpstreamManager()
        for upstream in config.upstreams:
            self._upstream_manager.add_upstream(upstream)
        self._indexer = ToolIndexer.from_config(config.embedding, config.vector_store)
        self._router = ToolRouter(self._upstream_manager, self._indexer)
        self._server: Server | None = None

    async def initialize(self) -> None:
        await self._upstream_manager.connect_all()
        await self._indexer.rebuild_index(self._upstream_manager)
        logger.info("proxy_initialized")

    async def shutdown(self) -> None:
        await self._router.graceful_shutdown()
        await self._upstream_manager.disconnect_all()
        await self._indexer.close()
        logger.info("proxy_shutdown_complete")

    async def list_tools(
        self,
        filter: str | None = None,
        refresh: bool = False,
    ) -> ListResult:
        if refresh:
            await self._indexer.rebuild_index(self._upstream_manager)
        server_info = await self._upstream_manager.refresh_all()
        total_tools = sum(info.tool_count for info in server_info.values())
        result = ListResult(
            servers=list(server_info.values()),
            total_tools=total_tools,
            index_age_s=self._indexer.get_index_age(),
        )
        if filter:
            filtered_servers: list[ServerInfo] = []
            for server in result.servers:
                filtered_tools = [
                    t
                    for t in server.tools
                    if filter in f"{server.server_id}.{t.tool_name}"
                ]
                if filtered_tools:
                    filtered_servers.append(
                        ServerInfo(
                            server_id=server.server_id,
                            display_name=server.display_name,
                            tool_count=len(filtered_tools),
                            tools=filtered_tools,
                            status=server.status,
                        )
                    )
            result.servers = filtered_servers
            result.total_tools = sum(s.tool_count for s in filtered_servers)
        return result

    async def search_tools(
        self,
        query: str,
        top_k: int = 5,
        server_filter: list[str] | None = None,
        score_threshold: float = 0.0,
    ) -> SearchResult:
        if not query:
            raise ValueError("query must be non-empty")
        tool_count = await self._indexer.get_tool_count()
        if tool_count == 0:
            raise IndexNotReadyError(
                "No tools indexed. Run list(refresh=True) to build the index."
            )
        results = await self._indexer.search(
            query, top_k, server_filter, score_threshold
        )
        search_results = [
            SearchResultItem(
                server_id=record.server_id,
                tool_name=record.tool_name,
                score=score,
                description=record.description,
                input_schema=record.input_schema,
                call_hint=(
                    f'To invoke: use tool_call with name="{record.tool_name}" '
                    f'and route to server_id="{record.server_id}".'
                ),
            )
            for record, score in results
        ]
        return SearchResult(
            results=search_results,
            query=query,
            index_age_s=self._indexer.get_index_age(),
        )

    def get_mcp_server(self) -> Server:
        if self._server is not None:
            return self._server

        server = Server("mcp-smart-proxy")

        @server.list_tools()
        async def list_tools_handler() -> list:
            return [
                {
                    "name": "list",
                    "description": "List known upstream tools, optionally filtered.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "filter": {
                                "type": "string",
                                "description": "Glob or substring to narrow results",
                            },
                            "refresh": {
                                "type": "boolean",
                                "description": "Re-introspect upstream servers",
                                "default": False,
                            },
                        },
                    },
                },
                {
                    "name": "search",
                    "description": "Semantic search over indexed tools.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Natural-language description",
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "Number of results to return (1-50)",
                                "default": 5,
                                "minimum": 1,
                                "maximum": 50,
                            },
                            "server_filter": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Server IDs to restrict search",
                            },
                            "score_threshold": {
                                "type": "number",
                                "description": "Min cosine similarity (0.0-1.0)",
                                "default": 0.0,
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                        },
                        "required": ["query"],
                    },
                },
            ]

        @server.call_tool()
        async def call_tool_handler(
            name: str, arguments: dict[str, Any] | None
        ) -> list[dict[str, Any]]:
            arguments = arguments or {}
            if name == "list":
                filter_val = arguments.get("filter")
                refresh_val = arguments.get("refresh", False)
                result = await self.list_tools(filter=filter_val, refresh=refresh_val)
                return [{"type": "text", "text": result.model_dump_json(indent=2)}]
            elif name == "search":
                try:
                    result = await self.search_tools(
                        query=arguments.get("query", ""),
                        top_k=arguments.get("top_k", 5),
                        server_filter=arguments.get("server_filter"),
                        score_threshold=arguments.get("score_threshold", 0.0),
                    )
                    return [{"type": "text", "text": result.model_dump_json(indent=2)}]
                except IndexNotReadyError as e:
                    return [{"type": "text", "text": str(e), "isError": True}]
                except ValueError as e:
                    return [{"type": "text", "text": str(e), "isError": True}]
            else:
                if "::" in name:
                    server_id, tool_name = name.split("::", 1)
                else:
                    return [
                        {
                            "type": "text",
                            "text": f"Unknown tool: {name}",
                            "isError": True,
                        }
                    ]
                result = await self._router.route_tool_call(
                    server_id, tool_name, arguments
                )
                return result.content

        self._server = server
        return server

    def get_upstream_manager(self) -> UpstreamManager:
        return self._upstream_manager

    def get_indexer(self) -> ToolIndexer:
        return self._indexer
