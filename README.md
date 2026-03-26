# mcp-smart-proxy

mcp-name: io.github.daedalus/mcp-smart-proxy


> Token-efficient MCP server gateway with semantic tool search

## Install

```bash
pip install -e .
```

## Usage

```python
from mcp_smart_proxy import MCPSmartProxyServer, load_config

config = load_config("proxy.yaml")
server = MCPSmartProxyServer(config)
```

## CLI

```bash
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

- `load_config(path)` - Load configuration from YAML or JSON file
- `validate_config(path)` - Validate configuration file

### Server

- `MCPSmartProxyServer` - Main server class

## Development

```bash
pip install -e ".[dev]"
pytest
ruff format src/ tests/
ruff check src/ tests/
mypy src/
```
