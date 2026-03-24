import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_config_dict():
    return {
        "proxy": {
            "transport": "stdio",
            "log_level": "DEBUG",
        },
        "upstreams": [
            {
                "id": "test-server",
                "display_name": "Test Server",
                "transport": "stdio",
                "command": ["echo", "test"],
            }
        ],
        "embedding": {
            "backend": "sentence-transformers",
            "model": "all-MiniLM-L6-v2",
        },
        "vector_store": {
            "backend": "chroma",
            "chroma": {
                "persist_directory": "./test_index",
            },
        },
    }


@pytest.fixture
def sample_tool_info():
    return {
        "name": "test_tool",
        "description": "A test tool for testing",
        "inputSchema": {
            "type": "object",
            "properties": {
                "arg1": {"type": "string"},
                "arg2": {"type": "number"},
            },
            "required": ["arg1"],
        },
    }


@pytest.fixture
def sample_server_info():
    return {
        "server_id": "test-server",
        "display_name": "Test Server",
        "tool_count": 2,
        "tools": [
            {
                "tool_name": "tool_one",
                "description": "First tool",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "tool_name": "tool_two",
                "description": "Second tool",
                "input_schema": {"type": "object", "properties": {}},
            },
        ],
    }
