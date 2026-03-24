import pytest
import yaml

from mcp_smart_proxy.config import validate_config


@pytest.fixture
def valid_config_file(temp_dir):
    config = {
        "proxy": {
            "transport": "stdio",
            "log_level": "INFO",
        },
        "upstreams": [
            {
                "id": "test",
                "display_name": "Test",
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
                "persist_directory": "./test",
            },
        },
    }
    path = temp_dir / "proxy.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


def test_validate_valid_config(valid_config_file):
    result = validate_config(valid_config_file)
    assert result is True


def test_validate_nonexistent_file():
    result = validate_config("/nonexistent/path.yaml")
    assert result is False
