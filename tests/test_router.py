import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_smart_proxy.models import ToolCallResult
from mcp_smart_proxy.router import ToolRouter


@pytest.fixture
def mock_upstream_manager():
    manager = MagicMock()
    manager.call_tool = AsyncMock(return_value=[{"type": "text", "content": "result"}])
    return manager


@pytest.fixture
def mock_indexer():
    indexer = MagicMock()
    return indexer


@pytest.fixture
def router(mock_upstream_manager, mock_indexer):
    return ToolRouter(mock_upstream_manager, mock_indexer)


@pytest.mark.asyncio
async def test_route_tool_call_success(router, mock_upstream_manager):
    result = await router.route_tool_call("test-server", "tool_name", {"arg": "value"})
    assert isinstance(result, ToolCallResult)
    assert result.is_error is False
    mock_upstream_manager.call_tool.assert_called_once_with(
        "test-server", "tool_name", {"arg": "value"}
    )


@pytest.mark.asyncio
async def test_route_tool_call_failure(router, mock_upstream_manager):
    mock_upstream_manager.call_tool.side_effect = ConnectionError("server unavailable")
    result = await router.route_tool_call("test-server", "tool_name", {})
    assert result.is_error is True
    assert "unavailable" in result.content[0]["text"]


@pytest.mark.asyncio
async def test_graceful_shutdown(router):
    task = asyncio.create_task(asyncio.sleep(0.001))
    router._in_flight_calls.add(task)
    await asyncio.sleep(0.002)
    await router.graceful_shutdown()
    assert len(router._in_flight_calls) == 0
