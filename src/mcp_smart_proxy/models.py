from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolInfo(BaseModel):
    tool_name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ServerInfo(BaseModel):
    server_id: str
    display_name: str
    tool_count: int
    tools: list[ToolInfo] = Field(default_factory=list)
    status: str = "healthy"


class ListResult(BaseModel):
    servers: list[ServerInfo] = Field(default_factory=list)
    total_tools: int = 0
    index_age_s: int | None = None


class SearchResultItem(BaseModel):
    server_id: str
    tool_name: str
    score: float
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    call_hint: str


class SearchResult(BaseModel):
    results: list[SearchResultItem] = Field(default_factory=list)
    query: str
    index_age_s: int | None = None


class ToolRecord(BaseModel):
    id: str
    server_id: str
    tool_name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    embed_text: str
    indexed_at: datetime = Field(default_factory=datetime.utcnow)


class ToolCallResult(BaseModel):
    content: list[dict[str, Any]] = Field(default_factory=list)
    is_error: bool = False


ToolResult = ToolCallResult


class IndexNotReadyError(Exception):
    pass


class UpstreamDisconnectedError(Exception):
    pass
