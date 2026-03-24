from __future__ import annotations

import asyncio
from pathlib import Path

import click
import structlog

from mcp_smart_proxy import __version__
from mcp_smart_proxy.config import load_config, validate_config
from mcp_smart_proxy.server import MCPSmartProxyServer

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
)

logger = structlog.get_logger(__name__)


@click.group()
@click.version_option(version=__version__)
def cli():
    pass


@cli.command()
@click.option(
    "--config",
    "-c",
    default="proxy.yaml",
    type=click.Path(exists=True),
    help="Path to proxy.yaml config file",
)
def serve(config: str):
    config_path = Path(config)
    cfg = load_config(config_path)
    server = MCPSmartProxyServer(cfg)
    asyncio.run(_serve_async(server, cfg))


async def _serve_async(server: MCPSmartProxyServer, cfg):
    from mcp.server import InitializationOptions
    from mcp.server.stdio import stdio_server

    await server.initialize()
    mcp_server = server.get_mcp_server()
    async with stdio_server(mcp_server) as (read_stream, write_stream):
        initialization_options = InitializationOptions(
            server_name="mcp-smart-proxy",
            server_version=__version__,
            capabilities={},
        )
        await mcp_server.run(
            read_stream,
            write_stream,
            initialization_options,
        )
    await server.shutdown()


@cli.command()
@click.option(
    "--config",
    "-c",
    default="proxy.yaml",
    type=click.Path(exists=True),
    help="Path to proxy.yaml config file",
)
def index(config: str):
    config_path = Path(config)
    cfg = load_config(config_path)
    server = MCPSmartProxyServer(cfg)
    asyncio.run(_index_async(server))


async def _index_async(server: MCPSmartProxyServer):
    try:
        await server.initialize()
        tool_count = await server.get_indexer().get_tool_count()
        click.echo(f"Index built successfully. {tool_count} tools indexed.")
    finally:
        await server.shutdown()


@cli.command()
@click.option(
    "--config",
    "-c",
    default="proxy.yaml",
    type=click.Path(exists=True),
    help="Path to proxy.yaml config file",
)
def status(config: str):
    config_path = Path(config)
    cfg = load_config(config_path)
    server = MCPSmartProxyServer(cfg)
    asyncio.run(_status_async(server))


async def _status_async(server: MCPSmartProxyServer):
    try:
        await server.initialize()
        upstream_manager = server.get_upstream_manager()
        indexer = server.get_indexer()
        server_info = await upstream_manager.refresh_all()
        tool_count = await indexer.get_tool_count()
        index_age = indexer.get_index_age()
        click.echo("Upstream servers:")
        for server_id, info in server_info.items():
            status_symbol = "✓" if info.status == "healthy" else "✗"
            click.echo(
                f"  {status_symbol} {info.display_name} ({server_id}): "
                f"{info.tool_count} tools"
            )
        click.echo(f"\nIndex: {tool_count} tools indexed")
        if index_age is not None:
            click.echo(f"Index age: {index_age}s")
    finally:
        await server.shutdown()


@cli.command()
@click.option(
    "--config",
    "-c",
    default="proxy.yaml",
    type=click.Path(exists=True),
    help="Path to proxy.yaml config file",
)
def validate(config: str):
    config_path = Path(config)
    if validate_config(config_path):
        click.echo("Configuration is valid.")
    else:
        click.echo("Configuration is invalid.", err=True)
        raise click.Exit(code=1)


def main():
    cli()


if __name__ == "__main__":
    main()
