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
mcp-smart-proxy index --config proxy.yaml
mcp-smart-proxy status --config proxy.yaml
mcp-smart-proxy validate --config proxy.yaml
```

## API

### Config

- `load_config(path)` - Load configuration from YAML file
- `validate_config(path)` - Validate configuration file

### Server

- `MCPSmartProxyServer` - Main server class

## Development

```bash
pip install -e ".[dev]"
pytest
black src/ tests/
ruff check src/ tests/
flake8 src/ tests/ --max-line-length=88 --extend-ignore=E203,W503
```
