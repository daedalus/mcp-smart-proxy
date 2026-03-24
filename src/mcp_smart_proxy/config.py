from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class TransportType(StrEnum):
    STDIO = "stdio"
    SSE = "sse"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ProxyConfig(BaseModel):
    transport: TransportType = TransportType.STDIO
    sse_port: int = 8765
    health_port: int = 9000
    log_level: LogLevel = LogLevel.INFO
    refresh_timeout_s: int = 30


class UpstreamTransportConfig(BaseModel):
    transport: TransportType
    url: str | None = None
    command: list[str] | None = None
    env: dict[str, str] = Field(default_factory=dict)
    restart_on_crash: bool = False


class UpstreamConfig(BaseModel):
    id: str
    display_name: str
    transport: TransportType
    url: str | None = None
    command: list[str] | None = None
    env: dict[str, str] = Field(default_factory=dict)
    restart_on_crash: bool = False

    def get_transport_config(self) -> UpstreamTransportConfig:
        return UpstreamTransportConfig(
            transport=self.transport,
            url=self.url,
            command=self.command,
            env=self.env,
            restart_on_crash=self.restart_on_crash,
        )


class EmbeddingBackend(StrEnum):
    SENTENCE_TRANSFORMERS = "sentence-transformers"
    OPENAI = "openai"
    OLLAMA = "ollama"


class EmbeddingConfig(BaseModel):
    backend: EmbeddingBackend = EmbeddingBackend.SENTENCE_TRANSFORMERS
    model: str = "all-MiniLM-L6-v2"
    openai_api_key: str | None = None
    ollama_url: str = "http://localhost:11434"


class VectorStoreBackend(StrEnum):
    CHROMA = "chroma"
    QDRANT = "qdrant"
    PGVECTOR = "pgvector"


class ChromaConfig(BaseModel):
    persist_directory: str = "./.mcp_proxy_index"


class QdrantConfig(BaseModel):
    url: str = "http://localhost:6333"
    collection: str = "mcp_tools"


class PgvectorConfig(BaseModel):
    dsn: str = "postgresql://user:pass@localhost/mcpdb"


class VectorStoreConfig(BaseModel):
    backend: VectorStoreBackend = VectorStoreBackend.CHROMA
    chroma: ChromaConfig = Field(default_factory=ChromaConfig)
    qdrant: QdrantConfig | None = None
    pgvector: PgvectorConfig | None = None


class Config(BaseModel):
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    upstreams: list[UpstreamConfig] = Field(default_factory=list)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)


def _apply_env_overrides(config_dict: dict[str, Any]) -> dict[str, Any]:
    env_prefix = "MCP_PROXY_"
    for key in os.environ:
        if not key.startswith(env_prefix):
            continue
        parts = key[len(env_prefix) :].lower().split("_")
        if len(parts) < 2:
            continue
        section = parts[0]
        field = "_".join(parts[1:])
        if section not in config_dict:
            config_dict[section] = {}
        config_dict[section][field] = os.environ[key]
    return config_dict


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        config_dict = yaml.safe_load(f) or {}

    config_dict = _apply_env_overrides(config_dict)
    return Config(**config_dict)


def validate_config(path: str | Path) -> bool:
    try:
        load_config(path)
        return True
    except Exception:
        return False
