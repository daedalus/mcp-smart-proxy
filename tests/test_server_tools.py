from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_smart_proxy.config import (
    Config,
    EmbeddingConfig,
    ProxyConfig,
    UpstreamConfig,
    VectorStoreConfig,
)
from mcp_smart_proxy.models import IndexNotReadyError, ServerInfo, ToolInfo
from mcp_smart_proxy.server import MCPSmartProxyServer


class MockEmbedder:
    async def embed(self, text):
        return [0.1, 0.2, 0.3]

    async def embed_batch(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def close(self):
        pass


class MockStore:
    async def add(self, records, embeddings):
        pass

    async def search(self, query_embedding, top_k, server_filter=None):
        return []

    async def clear(self):
        pass

    async def close(self):
        pass

    async def get_count(self):
        return 0


@pytest.fixture
def config():
    return Config(
        proxy=ProxyConfig(),
        upstreams=[
            UpstreamConfig(
                id="test-server",
                display_name="Test Server",
                transport="stdio",
                command=["echo", "test"],
            )
        ],
        embedding=EmbeddingConfig(),
        vector_store=VectorStoreConfig(),
    )


@pytest.fixture
def server(config):
    with (
        patch("mcp_smart_proxy.server.UpstreamManager") as MockManager,
        patch("mcp_smart_proxy.server.ToolIndexer") as MockIndexer,
    ):
        mock_manager = MagicMock()
        mock_manager.connect_all = AsyncMock()
        mock_manager.disconnect_all = AsyncMock()
        mock_manager.refresh_all = AsyncMock(return_value={})
        MockManager.return_value = mock_manager

        mock_indexer = MagicMock()
        mock_indexer.rebuild_index = AsyncMock()
        mock_indexer.get_index_age = MagicMock(return_value=None)
        mock_indexer.get_tool_count = AsyncMock(return_value=0)
        mock_indexer.search = AsyncMock(return_value=[])
        mock_indexer.close = AsyncMock()
        MockIndexer.return_value = mock_indexer

        return MCPSmartProxyServer(config)


@pytest.mark.asyncio
async def test_list_tools_empty(server):
    result = await server.list_tools()
    assert result.total_tools == 0
    assert len(result.servers) == 0


@pytest.mark.asyncio
async def test_list_tools_with_filter(server):
    server._upstream_manager.refresh_all = AsyncMock(
        return_value={
            "test-server": ServerInfo(
                server_id="test-server",
                display_name="Test Server",
                tool_count=2,
                tools=[
                    ToolInfo(
                        tool_name="tool1", description="First tool", input_schema={}
                    ),
                    ToolInfo(
                        tool_name="tool2", description="Second tool", input_schema={}
                    ),
                ],
                status="healthy",
            )
        }
    )
    result = await server.list_tools(filter="tool1")
    assert len(result.servers) == 1
    assert result.servers[0].tools[0].tool_name == "tool1"


@pytest.mark.asyncio
async def test_search_tools_empty_query(server):
    with pytest.raises(ValueError, match="query must be non-empty"):
        await server.search_tools(query="")


@pytest.mark.asyncio
async def test_search_tools_no_index(server):
    server._indexer.get_tool_count = AsyncMock(return_value=0)
    with pytest.raises(IndexNotReadyError):
        await server.search_tools(query="test")


@pytest.mark.asyncio
async def test_search_tools_with_results(server):
    from datetime import datetime

    from mcp_smart_proxy.models import ToolRecord

    server._indexer.get_tool_count = AsyncMock(return_value=1)
    server._indexer.search = AsyncMock(
        return_value=[
            (
                ToolRecord(
                    id="test::tool",
                    server_id="test",
                    tool_name="tool",
                    description="A test tool",
                    input_schema={},
                    embed_text="test",
                    indexed_at=datetime.utcnow(),
                ),
                0.9,
            )
        ]
    )
    result = await server.search_tools(query="test")
    assert len(result.results) == 1
    assert result.results[0].tool_name == "tool"


@pytest.mark.asyncio
async def test_search_tools_top_k_bounds(server):
    server._indexer.get_tool_count = AsyncMock(return_value=1)
    server._indexer.search = AsyncMock(return_value=[])
    result = await server.search_tools(query="test", top_k=100)
    assert result.results == []
