from __future__ import annotations

import asyncio
from datetime import datetime

import structlog

from mcp_smart_proxy.config import EmbeddingConfig, VectorStoreConfig
from mcp_smart_proxy.index.embedder import Embedder, create_embedder
from mcp_smart_proxy.index.store import VectorStore, create_vector_store
from mcp_smart_proxy.models import ServerInfo, ToolRecord
from mcp_smart_proxy.upstream.manager import UpstreamManager

logger = structlog.get_logger(__name__)

MAX_DESCRIPTION_LENGTH = 8192


class ToolIndexer:
    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
    ):
        self._embedder = embedder
        self._store = store
        self._indexed_at: datetime | None = None
        self._refresh_event: asyncio.Event | None = None

    @classmethod
    def from_config(
        cls, embedding_config: EmbeddingConfig, store_config: VectorStoreConfig
    ) -> ToolIndexer:
        embedder = create_embedder(embedding_config)
        store = create_vector_store(store_config)
        return cls(embedder, store)

    async def rebuild_index(self, upstream_manager: UpstreamManager) -> None:
        if self._refresh_event and not self._refresh_event.is_set():
            logger.info("refresh_already_in_progress_joining")
            await self._refresh_event.wait()
            return
        self._refresh_event = asyncio.Event()
        try:
            server_info = await upstream_manager.refresh_all()
            await self._index_servers(server_info)
            self._indexed_at = datetime.utcnow()
            logger.info("index_rebuilt", total_tools=await self._store.get_count())
        finally:
            self._refresh_event.set()

    async def _index_servers(self, server_info: dict[str, ServerInfo]) -> None:
        records: list[ToolRecord] = []
        for server_id, info in server_info.items():
            for tool in info.tools:
                description = tool.description
                if len(description) > MAX_DESCRIPTION_LENGTH:
                    description = description[:MAX_DESCRIPTION_LENGTH] + "[TRUNCATED]"
                property_names = list(tool.input_schema.get("properties", {}).keys())
                embed_text = (
                    f"{tool.tool_name} {tool.description} {' '.join(property_names)}"
                )
                record = ToolRecord(
                    id=f"{server_id}::{tool.tool_name}",
                    server_id=server_id,
                    tool_name=tool.tool_name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    embed_text=embed_text,
                    indexed_at=datetime.utcnow(),
                )
                records.append(record)
        if records:
            embeddings = await self._embedder.embed_batch(
                [r.embed_text for r in records]
            )
            await self._store.add(records, embeddings)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        server_filter: list[str] | None = None,
        score_threshold: float = 0.0,
    ) -> list[tuple[ToolRecord, float]]:
        if not query:
            raise ValueError("query must be non-empty")
        top_k = max(1, min(50, top_k))
        query_embedding = await self._embedder.embed(query)
        results = await self._store.search(query_embedding, top_k, server_filter)
        if score_threshold > 0:
            results = [(r, s) for r, s in results if s >= score_threshold]
        return results

    def get_index_age(self) -> int | None:
        if self._indexed_at is None:
            return None
        return int((datetime.utcnow() - self._indexed_at).total_seconds())

    async def get_tool_count(self) -> int:
        return await self._store.get_count()

    async def close(self) -> None:
        await self._embedder.close()
        await self._store.close()
