from unittest.mock import AsyncMock

import pytest

from mcp_smart_proxy.index.indexer import MAX_DESCRIPTION_LENGTH, ToolIndexer


class MockEmbedder:
    def __init__(self):
        self.embeddings: list[list[float]] = []

    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def close(self):
        pass


class MockStore:
    def __init__(self):
        self.records: list = []
        self.embeddings: list = []

    async def add(self, records, embeddings):
        self.records.extend(records)
        self.embeddings.extend(embeddings)

    async def search(self, query_embedding, top_k, server_filter=None):
        return []

    async def clear(self):
        self.records.clear()
        self.embeddings.clear()

    async def close(self):
        pass

    async def get_count(self):
        return len(self.records)


@pytest.fixture
def mock_embedder():
    return MockEmbedder()


@pytest.fixture
def mock_store():
    return MockStore()


@pytest.fixture
def indexer(mock_embedder, mock_store):
    return ToolIndexer(mock_embedder, mock_store)


def test_indexer_initialization(indexer):
    assert indexer._embedder is not None
    assert indexer._store is not None
    assert indexer.get_index_age() is None


@pytest.mark.asyncio
async def test_indexer_search_empty_query(indexer):
    with pytest.raises(ValueError, match="query must be non-empty"):
        await indexer.search("")


@pytest.mark.asyncio
async def test_indexer_search_with_results(indexer, mock_store):
    from datetime import datetime

    from mcp_smart_proxy.models import ToolRecord

    mock_store.search = AsyncMock(
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
    mock_store.get_count = AsyncMock(return_value=1)
    results = await indexer.search("test query")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_indexer_top_k_clamping(indexer):
    results = await indexer.search("test", top_k=100)
    assert len(results) <= 50


@pytest.mark.asyncio
async def test_indexer_get_tool_count(indexer, mock_store):
    count = await indexer.get_tool_count()
    assert count == 0


def test_max_description_length():
    assert MAX_DESCRIPTION_LENGTH == 8192
