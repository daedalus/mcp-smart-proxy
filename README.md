# MCPSmartProxy

> Token-efficient MCP server gateway with semantic tool search

[![PyPI](https://img.shields.io/pypi/v/mcp-smart-proxy.svg)](https://pypi.org/project/mcp-smart-proxy/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-smart-proxy.svg)](https://pypi.org/project/mcp-smart-proxy/)
[![Coverage](https://codecov.io/gh/daedalus/mcp-smart-proxy/branch/main/graph/badge.svg)](https://codecov.io/gh/daedalus/mcp-smart-proxy)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

mcp-name: io.github.daedalus/mcp-smart-proxy

## Install

```bash
pip install mcp-smart-proxy
```

## Usage

```python
from mcp_smart_proxy import ProxyConfig

config = ProxyConfig.from_file("proxy.yaml")
```

## CLI

```bash
mcp-smart-proxy --help
mcp-smart-proxy serve --config proxy.yaml
mcp-smart-proxy serve --config proxy.yaml --watch ./servers/
mcp-smart-proxy serve --config proxy.yaml --transport streamable-http --host 0.0.0.0 --port 8000
mcp-smart-proxy index --config proxy.yaml
mcp-smart-proxy status --config proxy.yaml
mcp-smart-proxy validate --config proxy.yaml
```

The `--watch` option monitors a directory for `.yaml`, `.yml`, or `.json` files containing
upstream server configurations. Add, modify, or remove files to dynamically update the
available servers at runtime.

### Transport Options

The `--transport` option supports:
- `stdio` (default) - Standard input/output transport for local MCP clients

## API

### Config

- `ProxyConfig` - Main configuration model
- `UpstreamConfig` - Upstream server configuration
- `EmbeddingConfig` - Embedding backend configuration
- `VectorStoreConfig` - Vector store backend configuration

### Models

- `ListResult` - Result from the `list` tool
- `SearchResult` - Result from the `search` tool
- `ToolResult` - Result from tool calls

## Development

```bash
git clone https://github.com/daedalus/mcp-smart-proxy.git
cd mcp-smart-proxy
pip install -e ".[test]"

# run tests
pytest

# format
ruff format src/ tests/

# lint
ruff check src/ tests/

# type check
mypy src/
```
