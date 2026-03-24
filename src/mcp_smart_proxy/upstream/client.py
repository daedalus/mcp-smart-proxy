from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class UpstreamClient(ABC):
    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def list_tools(self) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        pass

    @abstractmethod
    async def is_connected(self) -> bool:
        pass


class StdioUpstreamClient(UpstreamClient):
    def __init__(self, command: list[str], env: dict[str, str] | None = None):
        self.command = command
        self.env = env or {}
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        env = {**os.environ, **self.env} if self.env else None
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-smart-proxy", "version": "0.1.0"},
            },
        )
        await self._send_notification("initialized", {})
        logger.info("stdio_upstream_connected", command=self.command)

    async def disconnect(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
            await self._process.communicate()
        logger.info("stdio_upstream_disconnected")

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        result = await self._send_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )
        for content_item in result.get("content", []):
            yield content_item

    async def is_connected(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def _send_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if not self._process or not self._process.stdin:
            raise ConnectionError("Process not connected")
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        self._process.stdin.write((json.dumps(request) + "\n").encode())
        await self._process.stdin.drain()
        future = asyncio.Future()
        self._pending[self._request_id] = future
        return await future

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            return
        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        self._process.stdin.write((json.dumps(notification) + "\n").encode())
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        if not self._process or not self._process.stdout:
            return
        reader = self._process.stdout
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                message = json.loads(line.decode())
                if "id" in message:
                    request_id = message["id"]
                    if request_id in self._pending:
                        future = self._pending.pop(request_id)
                        if "error" in message:
                            future.set_exception(Exception(message["error"]))
                        else:
                            future.set_result(message.get("result", {}))
            except json.JSONDecodeError:
                logger.warning("invalid_json_from_upstream", line=line.decode())


class SSEUpstreamClient(UpstreamClient):
    def __init__(self, url: str):
        import httpx

        self.url = url
        self._client: httpx.AsyncClient | None = None
        self._event_source: asyncio.Task | None = None

    async def connect(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(timeout=30.0)
        async with self._client.stream("GET", self.url) as response:
            response.raise_for_status()
            logger.info("sse_upstream_connected", url=self.url)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
        logger.info("sse_upstream_disconnected")

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self._client:
            raise ConnectionError("Client not connected")
        response = await self._client.post(
            self.url.replace("/sse", "/rpc"),
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )
        result = response.json()
        return result.get("result", {}).get("tools", [])

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        if not self._client:
            raise ConnectionError("Client not connected")
        response = await self._client.post(
            self.url.replace("/sse", "/rpc"),
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        result = response.json()
        for content_item in result.get("result", {}).get("content", []):
            yield content_item

    async def is_connected(self) -> bool:
        return self._client is not None
