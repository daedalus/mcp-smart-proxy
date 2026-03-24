import yaml

from mcp_smart_proxy.config import (
    Config,
    EmbeddingBackend,
    EmbeddingConfig,
    LogLevel,
    ProxyConfig,
    TransportType,
    UpstreamConfig,
    VectorStoreBackend,
    VectorStoreConfig,
    load_config,
    validate_config,
)


def test_proxy_config_defaults():
    config = ProxyConfig()
    assert config.transport == TransportType.STDIO
    assert config.log_level == LogLevel.INFO
    assert config.refresh_timeout_s == 30


def test_upstream_config_stdio():
    config = UpstreamConfig(
        id="test",
        display_name="Test",
        transport=TransportType.STDIO,
        command=["echo", "test"],
    )
    assert config.transport == TransportType.STDIO
    assert config.command == ["echo", "test"]


def test_upstream_config_sse():
    config = UpstreamConfig(
        id="test",
        display_name="Test",
        transport=TransportType.SSE,
        url="http://localhost:8080/sse",
    )
    assert config.transport == TransportType.SSE
    assert config.url == "http://localhost:8080/sse"


def test_embedding_config_defaults():
    config = EmbeddingConfig()
    assert config.backend == EmbeddingBackend.SENTENCE_TRANSFORMERS
    assert config.model == "all-MiniLM-L6-v2"


def test_vector_store_config_defaults():
    config = VectorStoreConfig()
    assert config.backend == VectorStoreBackend.CHROMA
    assert config.chroma.persist_directory == "./.mcp_proxy_index"


def test_full_config():
    config = Config(
        proxy=ProxyConfig(transport=TransportType.SSE, sse_port=8765),
        upstreams=[
            UpstreamConfig(
                id="github",
                display_name="GitHub MCP",
                transport=TransportType.SSE,
                url="http://localhost:3001/sse",
            )
        ],
        embedding=EmbeddingConfig(
            backend=EmbeddingBackend.OPENAI, openai_api_key="test"
        ),
        vector_store=VectorStoreConfig(backend=VectorStoreBackend.CHROMA),
    )
    assert len(config.upstreams) == 1
    assert config.upstreams[0].id == "github"


def test_load_config_from_yaml(temp_dir, sample_config_dict):
    config_path = temp_dir / "proxy.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config_dict, f)
    config = load_config(config_path)
    assert config.proxy.transport == TransportType.STDIO
    assert len(config.upstreams) == 1
    assert config.upstreams[0].id == "test-server"


def test_validate_config_valid(temp_dir, sample_config_dict):
    config_path = temp_dir / "proxy.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config_dict, f)
    assert validate_config(config_path) is True


def test_validate_config_invalid():
    assert validate_config("/nonexistent/path.yaml") is False
