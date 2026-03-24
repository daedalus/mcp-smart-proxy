from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

from mcp_smart_proxy.config import EmbeddingBackend, EmbeddingConfig

logger = structlog.get_logger(__name__)


class Embedder(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class SentenceTransformersEmbedder(Embedder):
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        logger.info("sentence_transformers_loaded", model=model_name)

    async def embed(self, text: str) -> list[float]:
        import asyncio

        return await asyncio.to_thread(
            self._model.encode, text, convert_to_numpy=True
        ).tolist()  # type: ignore[no-any-return]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        return await asyncio.to_thread(
            self._model.encode, texts, convert_to_numpy=True
        ).tolist()  # type: ignore[no-any-return]

    async def close(self) -> None:
        pass


class OpenAIEmbedder(Embedder):
    def __init__(self, api_key: str, model: str = "text-embedding-ada-002"):
        import openai

        openai.api_key = api_key
        self._model = model
        self._client = openai.OpenAI(api_key=api_key)
        logger.info("openai_embedder_initialized", model=model)

    async def embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    async def close(self) -> None:
        pass


class OllamaEmbedder(Embedder):
    def __init__(self, base_url: str, model: str = "nomic-embed-text"):
        import httpx

        self.base_url = base_url
        self.model = model
        self._client = httpx.AsyncClient(timeout=30.0)
        logger.info("ollama_embedder_initialized", base_url=base_url, model=model)

    async def embed(self, text: str) -> list[float]:
        response = await self._client.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
        )
        response.raise_for_status()
        return response.json()["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for text in texts:
            embedding = await self.embed(text)
            results.append(embedding)
        return results

    async def close(self) -> None:
        await self._client.aclose()


def create_embedder(config: EmbeddingConfig) -> Embedder:
    if config.backend == EmbeddingBackend.SENTENCE_TRANSFORMERS:
        return SentenceTransformersEmbedder(config.model)
    elif config.backend == EmbeddingBackend.OPENAI:
        if not config.openai_api_key:
            raise ValueError("openai_api_key is required for openai backend")
        return OpenAIEmbedder(config.openai_api_key, config.model)
    elif config.backend == EmbeddingBackend.OLLAMA:
        return OllamaEmbedder(config.ollama_url, config.model)
    else:
        raise ValueError(f"unknown embedding backend: {config.backend}")
