from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    import asyncpg

from mcp_smart_proxy.config import (
    ChromaConfig,
    PgvectorConfig,
    QdrantConfig,
    VectorStoreBackend,
    VectorStoreConfig,
)
from mcp_smart_proxy.models import ToolRecord

logger = structlog.get_logger(__name__)


class VectorStore(ABC):
    @abstractmethod
    async def add(
        self, records: list[ToolRecord], embeddings: list[list[float]]
    ) -> None:
        pass

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        server_filter: list[str] | None = None,
    ) -> list[tuple[ToolRecord, float]]:
        pass

    @abstractmethod
    async def clear(self) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    async def get_count(self) -> int:
        pass


class ChromaVectorStore(VectorStore):
    def __init__(self, config: ChromaConfig):
        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.PersistentClient(
            path=config.persist_directory,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="mcp_tools",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "chroma_store_initialized", persist_directory=config.persist_directory
        )

    async def add(
        self, records: list[ToolRecord], embeddings: list[list[float]]
    ) -> None:
        import asyncio

        await asyncio.to_thread(
            self._collection.upsert,
            ids=[r.id for r in records],
            embeddings=embeddings,
            documents=[r.embed_text for r in records],
            metadatas=[
                {
                    "server_id": r.server_id,
                    "tool_name": r.tool_name,
                    "description": r.description,
                    "input_schema": json.dumps(r.input_schema),
                    "indexed_at": r.indexed_at.isoformat(),
                }
                for r in records
            ],
        )

    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        server_filter: list[str] | None = None,
    ) -> list[tuple[ToolRecord, float]]:
        import asyncio

        where_clause: dict[str, Any] | None = None
        if server_filter:
            where_clause = {"server_id": {"$in": server_filter}}
        results = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_clause,
        )
        output: list[tuple[ToolRecord, float]] = []
        if not results["ids"] or not results["ids"][0]:
            return output
        for i, doc_id in enumerate(results["ids"][0]):
            metadata = results["metadatas"][0][i]
            distance = results["distances"][0][i]
            score = 1.0 - distance
            embed_text = results["documents"][0][i] if results.get("documents") else ""
            record = ToolRecord(
                id=doc_id,
                server_id=metadata["server_id"],
                tool_name=metadata["tool_name"],
                description=metadata["description"],
                input_schema=json.loads(metadata["input_schema"]),
                embed_text=embed_text,
                indexed_at=datetime.fromisoformat(metadata["indexed_at"]),
            )
            output.append((record, score))
        return output

    async def clear(self) -> None:
        import asyncio

        await asyncio.to_thread(self._client.delete_collection, "mcp_tools")
        self._collection = self._client.get_or_create_collection(
            name="mcp_tools",
            metadata={"hnsw:space": "cosine"},
        )

    async def close(self) -> None:
        pass

    async def get_count(self) -> int:
        return self._collection.count()


class QdrantVectorStore(VectorStore):
    def __init__(self, config: QdrantConfig):
        from qdrant_client import AsyncQdrantClient

        self._client = AsyncQdrantClient(url=config.url)
        self._collection_name = config.collection
        logger.info(
            "qdrant_store_initialized", url=config.url, collection=config.collection
        )

    async def add(
        self, records: list[ToolRecord], embeddings: list[list[float]]
    ) -> None:
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(
                id=i,
                vector=embeddings[i],
                payload={
                    "server_id": r.server_id,
                    "tool_name": r.tool_name,
                    "description": r.description,
                    "input_schema": json.dumps(r.input_schema),
                    "embed_text": r.embed_text,
                    "indexed_at": r.indexed_at.isoformat(),
                },
            )
            for i, r in enumerate(records)
        ]
        await self._client.upsert(
            collection_name=self._collection_name,
            points=points,
        )

    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        server_filter: list[str] | None = None,
    ) -> list[tuple[ToolRecord, float]]:
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        filter_clause: Filter | None = None
        if server_filter:
            filter_clause = Filter(
                must=[
                    FieldCondition(key="server_id", match=MatchAny(value=server_filter))
                ]
            )
        results = await self._client.search(
            collection_name=self._collection_name,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=filter_clause,
        )
        output: list[tuple[ToolRecord, float]] = []
        for result in results:
            payload = result.payload
            record = ToolRecord(
                id=f"{payload['server_id']}::{payload['tool_name']}",
                server_id=payload["server_id"],
                tool_name=payload["tool_name"],
                description=payload["description"],
                input_schema=json.loads(payload["input_schema"]),
                embed_text=payload["embed_text"],
                indexed_at=datetime.fromisoformat(payload["indexed_at"]),
            )
            output.append((record, result.score))
        return output

    async def clear(self) -> None:
        await self._client.delete(collection_name=self._collection_name, filter={})

    async def close(self) -> None:
        await self._client.close()

    async def get_count(self) -> int:
        info = await self._client.get_collection(collection_name=self._collection_name)
        return info.points_count


class PgvectorVectorStore(VectorStore):
    def __init__(self, config: PgvectorConfig):
        self._config = config
        self._pool: asyncpg.Pool | None = None
        logger.info("pgvector_store_initialized", dsn=config.dsn)

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(self._config.dsn)
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS mcp_tools (
                        id TEXT PRIMARY KEY,
                        server_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        description TEXT,
                        input_schema JSONB,
                        embed_text TEXT,
                        indexed_at TIMESTAMP,
                        embedding vector(384)
                    );
                    CREATE INDEX IF NOT EXISTS mcp_tools_embedding_idx
                    ON mcp_tools USING hnsw (embedding vector_cosine_ops);
                    """)
        return self._pool

    async def add(
        self, records: list[ToolRecord], embeddings: list[list[float]]
    ) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            for record, embedding in zip(records, embeddings):
                await conn.execute(
                    """
                    INSERT INTO mcp_tools (
                        id, server_id, tool_name, description,
                        input_schema, embed_text, indexed_at, embedding
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (id) DO UPDATE SET
                        server_id = EXCLUDED.server_id,
                        tool_name = EXCLUDED.tool_name,
                        description = EXCLUDED.description,
                        input_schema = EXCLUDED.input_schema,
                        embed_text = EXCLUDED.embed_text,
                        indexed_at = EXCLUDED.indexed_at,
                        embedding = EXCLUDED.embedding
                    """,
                    record.id,
                    record.server_id,
                    record.tool_name,
                    record.description,
                    json.dumps(record.input_schema),
                    record.embed_text,
                    record.indexed_at,
                    embedding,
                )

    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        server_filter: list[str] | None = None,
    ) -> list[tuple[ToolRecord, float]]:
        pool = await self._ensure_pool()
        query = """
            SELECT id, server_id, tool_name, description,
                   input_schema, embed_text, indexed_at,
                   1 - (embedding <=> $1) as score
            FROM mcp_tools
        """
        params: list[Any] = [query_embedding]
        if server_filter:
            query += f" WHERE server_id = ANY(${len(params) + 1})"
            params.append(server_filter)
        query += f" ORDER BY embedding <=> $1 LIMIT ${len(params) + 1}"
        params.append(top_k)
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        output: list[tuple[ToolRecord, float]] = []
        for row in rows:
            record = ToolRecord(
                id=row["id"],
                server_id=row["server_id"],
                tool_name=row["tool_name"],
                description=row["description"],
                input_schema=row["input_schema"],
                embed_text=row["embed_text"],
                indexed_at=row["indexed_at"],
            )
            output.append((record, row["score"]))
        return output

    async def clear(self) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM mcp_tools")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def get_count(self) -> int:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM mcp_tools")


def create_vector_store(config: VectorStoreConfig) -> VectorStore:
    if config.backend == VectorStoreBackend.CHROMA:
        return ChromaVectorStore(config.chroma)
    elif config.backend == VectorStoreBackend.QDRANT:
        if not config.qdrant:
            raise ValueError("qdrant config is required for qdrant backend")
        return QdrantVectorStore(config.qdrant)
    elif config.backend == VectorStoreBackend.PGVECTOR:
        if not config.pgvector:
            raise ValueError("pgvector config is required for pgvector backend")
        return PgvectorVectorStore(config.pgvector)
    else:
        raise ValueError(f"unknown vector store backend: {config.backend}")
