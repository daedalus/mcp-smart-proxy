__version__ = "0.1.0"

from mcp_smart_proxy.config import (
    EmbeddingConfig,
    ProxyConfig,
    UpstreamConfig,
    VectorStoreConfig,
)
from mcp_smart_proxy.models import (
    ListResult,
    SearchResult,
    ToolResult,
)

__all__ = [
    "__version__",
    "ListResult",
    "SearchResult",
    "ToolResult",
    "ProxyConfig",
    "UpstreamConfig",
    "EmbeddingConfig",
    "VectorStoreConfig",
]
