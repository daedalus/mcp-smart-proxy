from __future__ import annotations

import asyncio
from typing import Any

import structlog

from mcp_smart_proxy.index.indexer import ToolIndexer
from mcp_smart_proxy.models import (
    ToolCallResult,
)
from mcp_smart_proxy.upstream.manager import UpstreamManager

logger = structlog.get_logger(__name__)


class ToolRouter:
    def __init__(self, upstream_manager: UpstreamManager, indexer: ToolIndexer):
        self._upstream_manager = upstream_manager
        self._indexer = indexer
        self._in_flight_calls: set[asyncio.Task] = set()

    async def route_tool_call(
        self, server_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> ToolCallResult:
        try:
            content = await self._upstream_manager.call_tool(
                server_id, tool_name, arguments
            )
            return ToolCallResult(content=content, is_error=False)
        except ConnectionError as e:
            logger.error(
                "upstream_call_failed",
                server_id=server_id,
                tool=tool_name,
                error=str(e),
            )
            return ToolCallResult(
                content=[
                    {"type": "text", "text": f"upstream unavailable: {server_id}"}
                ],
                is_error=True,
            )
        except Exception as e:
            logger.error(
                "tool_call_exception", server_id=server_id, tool=tool_name, error=str(e)
            )
            return ToolCallResult(
                content=[{"type": "text", "text": str(e)}],
                is_error=True,
            )

    async def graceful_shutdown(self) -> None:
        if self._in_flight_calls:
            await asyncio.gather(*self._in_flight_calls, return_exceptions=True)
            self._in_flight_calls.clear()
