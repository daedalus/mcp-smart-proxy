from __future__ import annotations

import asyncio
from typing import Any

import structlog

from mcp_smart_proxy.config import UpstreamConfig
from mcp_smart_proxy.models import ServerInfo, ToolInfo
from mcp_smart_proxy.upstream.client import (
    SSEUpstreamClient,
    StdioUpstreamClient,
    UpstreamClient,
)

logger = structlog.get_logger(__name__)


class UpstreamManager:
    def __init__(self):
        self._clients: dict[str, UpstreamClient] = {}
        self._configs: dict[str, UpstreamConfig] = {}

    def add_upstream(self, config: UpstreamConfig) -> None:
        if config.id in self._configs:
            logger.warning("upstream_already_exists", server_id=config.id)
            return
        self._configs[config.id] = config
        logger.info(
            "upstream_configured", server_id=config.id, transport=config.transport
        )

    def remove_upstream(self, server_id: str) -> None:
        if server_id not in self._configs:
            logger.warning("upstream_not_found", server_id=server_id)
            return
        if server_id in self._clients:
            client = self._clients.pop(server_id)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(client.disconnect())
            except RuntimeError:
                pass
        del self._configs[server_id]
        logger.info("upstream_removed", server_id=server_id)

    async def connect_all(self) -> None:
        for server_id, config in self._configs.items():
            try:
                client = self._create_client(config)
                await client.connect()
                self._clients[server_id] = client
                logger.info("upstream_connected", server_id=server_id)
            except Exception as e:
                logger.error(
                    "upstream_connection_failed", server_id=server_id, error=str(e)
                )

    async def disconnect_all(self) -> None:
        for server_id, client in list(self._clients.items()):
            try:
                await client.disconnect()
                logger.info("upstream_disconnected", server_id=server_id)
            except Exception as e:
                logger.error(
                    "upstream_disconnect_failed", server_id=server_id, error=str(e)
                )
        self._clients.clear()

    async def refresh_all(self) -> dict[str, ServerInfo]:
        results: dict[str, ServerInfo] = {}
        for server_id, config in self._configs.items():
            client = self._clients.get(server_id)
            if client:
                try:
                    if not await client.is_connected():
                        await client.connect()
                        self._clients[server_id] = client
                except Exception as e:
                    logger.warning(
                        "upstream_reconnect_failed", server_id=server_id, error=str(e)
                    )
                    results[server_id] = ServerInfo(
                        server_id=config.id,
                        display_name=config.display_name,
                        tool_count=0,
                        status="error",
                    )
                    continue
                try:
                    tools = await client.list_tools()
                    tool_infos = [
                        ToolInfo(
                            tool_name=t.get("name", ""),
                            description=t.get("description", ""),
                            input_schema=t.get("inputSchema", {}),
                        )
                        for t in tools
                    ]
                    results[server_id] = ServerInfo(
                        server_id=config.id,
                        display_name=config.display_name,
                        tool_count=len(tool_infos),
                        tools=tool_infos,
                        status="healthy",
                    )
                except Exception as e:
                    logger.warning(
                        "upstream_list_failed", server_id=server_id, error=str(e)
                    )
                    results[server_id] = ServerInfo(
                        server_id=config.id,
                        display_name=config.display_name,
                        tool_count=0,
                        status="error",
                    )
            else:
                results[server_id] = ServerInfo(
                    server_id=config.id,
                    display_name=config.display_name,
                    tool_count=0,
                    status="error",
                )
        return results

    async def call_tool(
        self, server_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> list[dict[str, Any]]:
        client = self._clients.get(server_id)
        if not client or not await client.is_connected():
            raise ConnectionError(f"upstream unavailable: {server_id}")
        result: list[dict[str, Any]] = []
        async for chunk in client.call_tool(tool_name, arguments):
            result.append(chunk)
        return result

    def get_client(self, server_id: str) -> UpstreamClient | None:
        return self._clients.get(server_id)

    def _create_client(self, config: UpstreamConfig) -> UpstreamClient:
        if config.transport.value == "stdio":
            if not config.command:
                raise ValueError(f"stdio transport requires command for {config.id}")
            return StdioUpstreamClient(config.command, config.env)
        elif config.transport.value == "sse":
            if not config.url:
                raise ValueError(f"sse transport requires url for {config.id}")
            return SSEUpstreamClient(config.url)
        else:
            raise ValueError(f"unknown transport: {config.transport}")
