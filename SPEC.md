# SPEC.md — mcp-smart-proxy

## Purpose

`mcp-smart-proxy` is a token-efficient Model Context Protocol (MCP) server that acts as
a single unified gateway in front of an arbitrary collection of upstream MCP servers.
Instead of exposing every tool from every upstream server — which forces the LLM to read
a long, noisy tool list on every request — the proxy exposes exactly **two** tools:
`list` and `search`. The LLM calls `search` to discover which upstream tool to invoke,
then the proxy routes the actual call transparently. This collapses N×M tool descriptions
into a two-tool surface, dramatically reducing prompt-token consumption per turn.

Routing intelligence is backed by an optional vector database (default: in-process
ChromaDB). At startup (or on explicit refresh), the proxy introspects all upstream servers
via their `tools/list` MCP endpoint, embeds each tool's name + description, and upserts
the vectors. At query time `search` performs ANN retrieval and returns the best-matching
tools with their full schemas, ready for the LLM to pick and call. The proxy then
forwards the call, handles the MCP wire protocol, and streams the result back.

---

## Scope

### In scope

- MCP server (STDIO and SSE transport) that exposes exactly two tools: `list` and `search`.
- Client-side MCP connections to N upstream servers (STDIO and SSE transports).
- Automatic upstream introspection at startup and on-demand via `list(refresh=True)`.
- Vector-index building from upstream tool metadata (name, description, input schema summary).
- Semantic `search` over indexed tools, returning ranked candidates with full JSON schemas.
- Transparent call routing: forward a tool call to the correct upstream server and relay
  its result verbatim.
- Pluggable embedding backend (default: sentence-transformers `all-MiniLM-L6-v2`, locally,
  no external API required).
- Pluggable vector store backend (default: ChromaDB in-process; optional: Qdrant, pgvector).
- Configuration via a single YAML/JSON file (`proxy.yaml` or `proxy.json`) and environment variables.
- CLI entry point `mcp-smart-proxy` with `serve`, `index`, `status`, and `validate` subcommands.
- Dynamic upstream server loading via `--watch` / `-w` option: monitor a directory for new
  `.yaml`, `.yml`, or `.json` files containing upstream server configurations, load them
  automatically at runtime without restart.
- Structured JSON logging (configurable level).
- Graceful shutdown: drain in-flight upstream calls before exit.
- Health/readiness endpoint on a dedicated HTTP port (for container orchestration).

### Out of scope

- Authentication / authorization of downstream LLM clients (delegated to infrastructure).
- Upstream server authentication beyond what the upstream config specifies (e.g., bearer
  tokens passed through config are forwarded, but OAuth flows are not implemented).
- Tool result caching / deduplication.
- Multi-tenant isolation.
- GUI or web dashboard.
- Support for MCP resource endpoints (only `tools/*` namespace is proxied).

---

## Public API / Interface

### MCP Tools (exposed to the LLM client)

#### `list`

```
list(
    filter: str | None = None,
    refresh: bool = False
) -> ListResult
```

Returns the catalogue of all known upstream tools, grouped by upstream server.

- `filter`: optional glob or substring to narrow results (applied to `server_name.tool_name`).
- `refresh`: if `True`, re-introspects all upstream servers before returning, then
  rebuilds the vector index. Blocks until complete (max `config.refresh_timeout_s` seconds).
- Returns a `ListResult` object serialised as JSON:

```jsonc
{
  "servers": [
    {
      "server_id": "github",
      "display_name": "GitHub MCP",
      "tool_count": 12,
      "tools": [
        {
          "tool_name": "create_issue",
          "description": "Opens a new GitHub issue in the specified repository.",
          "input_schema": { /* JSON Schema object */ }
        }
      ]
    }
  ],
  "total_tools": 34,
  "index_age_s": 120
}
```

- Error behavior: if an upstream server is unreachable during refresh, it is marked
  `"status": "error"` in the result; other servers are unaffected.
- Invariant: always returns at least one server entry if the proxy has a non-empty
  upstream list, even if all are in error state.

---

#### `search`

```
search(
    query: str,
    top_k: int = 5,
    server_filter: list[str] | None = None,
    score_threshold: float = 0.0
) -> SearchResult
```

Performs semantic similarity search over the tool index and returns the top-k matching
tools with their full schemas, ready for the LLM to select and invoke.

- `query`: natural-language description of what the caller wants to do.
- `top_k`: number of results to return (1–50, clamped).
- `server_filter`: optional list of `server_id` values; restricts search to those servers.
- `score_threshold`: minimum cosine similarity score (0.0–1.0); results below this are
  dropped even if they are in the top-k.
- Returns a `SearchResult` serialised as JSON:

```jsonc
{
  "results": [
    {
      "server_id": "github",
      "tool_name": "create_issue",
      "score": 0.91,
      "description": "Opens a new GitHub issue...",
      "input_schema": { /* JSON Schema */ },
      "call_hint": "To invoke: use tool_call with name=\"create_issue\" and route to server_id=\"github\"."
    }
  ],
  "query": "open a bug report on GitHub",
  "index_age_s": 120
}
```

- Error behavior: if the vector index is empty (no upstream discovered yet), raises
  `IndexNotReadyError` with a message instructing the caller to run `list(refresh=True)`.
- Invariant: results are sorted descending by `score`.

---

#### `call` (internal routing — NOT exposed as an MCP tool to LLM)

```
call(
    server_id: str,
    tool_name: str,
    arguments: dict
) -> ToolResult
```

This is the proxy's internal dispatch method invoked when the LLM issues a standard MCP
`tools/call` request (routed by tool name if the upstream tool was directly advertised,
or explicitly by `server_id.tool_name` notation). Not a top-level MCP tool; handled
transparently at the protocol level.

- Resolves `server_id` → upstream connection.
- Forwards `tools/call` with `tool_name` and `arguments` verbatim.
- Streams `content` chunks back to the downstream client as they arrive.
- Error behavior: if the upstream returns an MCP error, it is relayed with the original
  error code; if the connection is lost mid-stream, raises `UpstreamDisconnectedError`.

---

### CLI Commands

| Command | Description |
|---|---|
| `mcp-smart-proxy serve` | Start the proxy server (STDIO or SSE, per config). |
| `mcp-smart-proxy serve --watch <dir>` | Start the proxy and watch a directory for dynamic upstream configs. |
| `mcp-smart-proxy index` | Re-introspect all upstreams and rebuild the vector index, then exit. |
| `mcp-smart-proxy status` | Print upstream connectivity and index stats, then exit. |
| `mcp-smart-proxy validate` | Validate `proxy.yaml` (or `.json`) schema and exit 0/1. |

---

### Configuration Format (`proxy.yaml`)

```yaml
proxy:
  transport: stdio          # "stdio" | "sse"
  sse_port: 8765            # only for sse transport
  health_port: 9000         # HTTP health endpoint port
  log_level: INFO           # DEBUG | INFO | WARNING | ERROR
  refresh_timeout_s: 30

upstreams:
  - id: github
    display_name: GitHub MCP
    transport: sse
    url: http://localhost:3001/sse
    env: {}                 # extra env vars forwarded to upstream (for stdio upstreams)

  - id: filesystem
    display_name: Filesystem MCP
    transport: stdio
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

embedding:
  backend: sentence-transformers   # "sentence-transformers" | "openai" | "ollama"
  model: all-MiniLM-L6-v2
  # openai_api_key: ${OPENAI_API_KEY}   # only for openai backend
  # ollama_url: http://localhost:11434   # only for ollama backend

vector_store:
  backend: chroma           # "chroma" | "qdrant" | "pgvector"
  chroma:
    persist_directory: ./.mcp_proxy_index
  # qdrant:
  #   url: http://localhost:6333
  #   collection: mcp_tools
  # pgvector:
  #   dsn: postgresql://user:pass@localhost/mcpdb
```

Environment variable overrides follow the pattern `MCP_PROXY_<SECTION>_<KEY>` (uppercase,
underscores). Example: `MCP_PROXY_PROXY_LOG_LEVEL=DEBUG`.

### Dynamic Upstream Configuration (--watch directory)

When using `--watch <directory>`, the proxy monitors the specified directory for new
`.yaml`, `.yml`, or `.json` files. Each file should contain a single upstream server
configuration (not an array):

```yaml
# e.g., servers/github.yaml
id: github
display_name: GitHub MCP
transport: sse
url: http://localhost:3001/sse
```

```json
// e.g., servers/filesystem.json
{
  "id": "filesystem",
  "display_name": "Filesystem MCP",
  "transport": "stdio",
  "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
}
```

Adding, modifying, or removing files in the watched directory dynamically adds,
updates, or removes upstream servers at runtime.

---

## Data Formats

### Tool Record (stored in vector DB)

```json
{
  "id": "github::create_issue",
  "server_id": "github",
  "tool_name": "create_issue",
  "description": "Opens a new GitHub issue in the specified repository.",
  "input_schema": { "type": "object", "properties": { "repo": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"} }, "required": ["repo", "title"] },
  "embed_text": "create_issue Opens a new GitHub issue in the specified repository. repo title body",
  "indexed_at": "2026-03-24T12:00:00Z"
}
```

`embed_text` is the concatenation of `tool_name`, `description`, and all top-level
property names from `input_schema` — this is the text that is embedded into the vector.

### MCP Wire Protocol

The proxy speaks MCP 2024-11-05 (current spec revision) over JSON-RPC 2.0. Upstream
connections also use MCP; any future spec revision must be handled via a protocol
negotiation layer in `upstream/client.py`.

---

## Edge Cases

1. **Upstream with zero tools**: a server that advertises an empty `tools/list` is
   recorded with `tool_count: 0` and contributes no vectors; subsequent searches silently
   skip it. `list()` still shows it as healthy.

2. **Duplicate tool names across servers**: two upstreams may both define a tool called
   `read_file`. They are stored as `filesystem::read_file` and `s3::read_file`. The
   `search` result's `call_hint` explicitly includes the `server_id` to disambiguate.
   The proxy never silently drops a duplicate.

3. **Upstream goes offline after index build**: if a routed `call` reaches a downed
   server, the proxy returns an MCP error `{ "code": -32001, "message": "upstream
   unavailable: <server_id>" }` without crashing. The index is not invalidated; the tool
   still appears in `search` results but with a note in status.

4. **Very large tool descriptions**: descriptions exceeding 8 192 characters are
   truncated to 8 192 characters before embedding (with a `[TRUNCATED]` suffix). The full
   description is still stored in metadata and returned to the LLM verbatim.

5. **Empty `query` string in `search`**: raises `ValueError("query must be non-empty")`
   with MCP error code `-32602` (invalid params).

6. **`refresh=True` while a refresh is already in progress**: the second call joins the
   in-progress refresh (deduplicated via an asyncio Event) rather than spawning a second
   introspection run.

7. **STDIO upstream process crashes mid-stream**: the proxy catches `BrokenPipeError`,
   attempts one restart (if `restart_on_crash: true` in upstream config), and relays a
   structured error to the client if restart fails.

8. **Vector store persistence corruption**: if the on-disk Chroma DB fails to load at
   startup, the proxy logs a warning, wipes and re-creates the collection, and schedules
   an automatic re-index of all upstreams before accepting requests.

9. **`top_k` larger than number of indexed tools**: returns all available tools without
   error; actual result count may be less than `top_k`.

10. **Embedding model unavailable at startup**: proxy exits with code 2 and a clear error
    message rather than starting in a degraded state where `search` would always fail.

---

## Performance & Constraints

- **Index build latency**: full re-index of 500 tools must complete in under 10 seconds
  on a laptop-class CPU (sentence-transformers backend, batch encoding).
- **Search latency**: p99 < 50 ms for ANN retrieval over 10 000 indexed tools (ChromaDB
  in-process).
- **Memory footprint**: under 512 MB RSS with sentence-transformers model loaded and a
  10 000-tool index in ChromaDB.
- **Concurrency**: must handle at least 32 concurrent in-flight tool calls (asyncio-based;
  no thread-per-request).
- **Token savings target**: for a typical setup with 5 upstream servers × 20 tools each
  (100 tools), the two-tool proxy surface saves ~95% of tool-description tokens per turn
  compared to full exposure.
- **Forbidden synchronous I/O in async paths**: all upstream network calls must use
  `asyncio`-compatible I/O (httpx async, asyncio subprocess). Blocking calls in the event
  loop are a hard defect.
- **Python ≥ 3.11** required (uses `asyncio.TaskGroup`, `tomllib`, `StrEnum`).
- **No C extensions in the proxy core** (sentence-transformers and chromadb may use them;
  the proxy's own code must be pure Python).

---

## Dependencies

| Package | Purpose |
|---|---|
| `mcp` (official SDK) | MCP server + client wire protocol |
| `httpx[asyncio]` | SSE upstream HTTP transport |
| `sentence-transformers` | Default local embedding backend |
| `chromadb` | Default in-process vector store |
| `pyyaml` | Config file parsing |
| `click` | CLI |
| `structlog` | Structured JSON logging |
| `pydantic >= 2` | Config and result model validation |
| `watchdog` | File system watching for dynamic upstream loading |

Optional / pluggable:

| Package | Purpose |
|---|---|
| `openai` | OpenAI embedding backend |
| `qdrant-client` | Qdrant vector store backend |
| `asyncpg` + `pgvector` | pgvector backend |

---

## Project Layout

```
mcp-smart-proxy/
├── SPEC.md
├── README.md
├── .gitignore
├── pyproject.toml
├── proxy.yaml.example
├── src/
│   └── mcp_smart_proxy/
│       ├── __init__.py          # version + public re-exports
│       ├── __main__.py          # python -m mcp_smart_proxy entry
│       ├── cli.py               # click CLI (serve/index/status/validate)
│       ├── config.py            # pydantic config models + YAML/JSON loader
│       ├── server.py            # MCP server: exposes list + search tools
│       ├── router.py            # routes tool calls to correct upstream
│       ├── watcher.py           # directory watcher for dynamic upstream loading
│       ├── upstream/
│       │   ├── __init__.py
│       │   ├── client.py        # async MCP client (STDIO + SSE)
│       │   └── manager.py       # manages pool of upstream connections
│       ├── index/
│       │   ├── __init__.py
│       │   ├── embedder.py      # pluggable embedding backends
│       │   ├── store.py         # pluggable vector store backends
│       │   └── indexer.py       # orchestrates introspect → embed → upsert
│       └── models.py            # shared Pydantic models (ListResult, SearchResult, …)
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_config.py
    ├── test_indexer.py
    ├── test_server_tools.py     # list + search MCP tool behavior
    ├── test_router.py
    └── test_cli.py
```

---

## Version

v0.1.0
