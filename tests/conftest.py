"""Pytest fixtures for Artemis CLI tests."""
import json
import os
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

# Add scripts directory to path for imports
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from artemis_cli.cli import app


@pytest.fixture
def cli_runner() -> CliRunner:
    """Create a CliRunner for testing Typer commands."""
    return CliRunner(mix_stderr=False)


@pytest.fixture
def temp_config(tmp_path: Path, monkeypatch) -> Path:
    """Create temporary config directory for testing.

    Patches CONFIG_DIR and CONFIG_FILE to use temp directory.
    """
    config_dir = tmp_path / ".artemis"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"

    # Patch the config paths in both api and cli modules
    monkeypatch.setattr("artemis_cli.api.CONFIG_DIR", config_dir)
    monkeypatch.setattr("artemis_cli.api.CONFIG_FILE", config_file)
    monkeypatch.setattr("artemis_cli.cli.CONFIG_DIR", config_dir)
    monkeypatch.setattr("artemis_cli.cli.CONFIG_FILE", config_file)

    return config_dir


@pytest.fixture
def mock_api():
    """Mock API requests.

    Yields a mock that can be configured to return specific responses.

    Example:
        def test_something(mock_api):
            mock_api.return_value = {"status": "ok"}
            # ... test code ...
    """
    with patch("artemis_cli.cli._api_request") as mock:
        yield mock


@pytest.fixture
def mock_api_module():
    """Mock the entire api module's api_request function.

    Use this for testing CLI commands that catch and handle APIError.
    """
    with patch("artemis_cli.api.api_request") as mock:
        yield mock


@pytest.fixture
def env_api_key(monkeypatch):
    """Set ARTEMIS_API_KEY environment variable."""
    monkeypatch.setenv("ARTEMIS_API_KEY", "art_test_key_for_testing")
    return "art_test_key_for_testing"


@pytest.fixture
def env_master_key(monkeypatch):
    """Set MASTER_API_KEY environment variable."""
    monkeypatch.setenv("MASTER_API_KEY", "test_master_key")
    return "test_master_key"


@pytest.fixture
def env_url(monkeypatch):
    """Set ARTEMIS_URL environment variable."""
    monkeypatch.setenv("ARTEMIS_URL", "http://localhost:8767")
    return "http://localhost:8767"


@pytest.fixture
def clean_env(monkeypatch):
    """Remove all Artemis environment variables."""
    monkeypatch.delenv("ARTEMIS_API_KEY", raising=False)
    monkeypatch.delenv("ARTEMIS_URL", raising=False)
    monkeypatch.delenv("MASTER_API_KEY", raising=False)


# Common mock responses
@pytest.fixture
def mock_service_account_response():
    """Standard service account creation response."""
    return {
        "service_account": {
            "id": "sa-123",
            "name": "test-service",
            "created_at": "2024-01-01T00:00:00Z"
        },
        "group": {
            "id": "group-456",
            "name": "test-service-group"
        },
        "api_key": {
            "id": "key-789",
            "key": "art_test_generated_key_abc123",
            "key_prefix": "art_test_gen"
        }
    }


@pytest.fixture
def mock_accounts_list_response():
    """Standard service accounts list response."""
    return {
        "service_accounts": [
            {
                "id": "sa-1",
                "name": "service-one",
                "created_at": "2024-01-01T00:00:00Z"
            },
            {
                "id": "sa-2",
                "name": "service-two",
                "created_at": "2024-01-02T00:00:00Z"
            }
        ]
    }


@pytest.fixture
def mock_embedding_response():
    """Standard embedding response."""
    return {
        "object": "list",
        "model": "text-embedding-3-small",
        "data": [
            {
                "object": "embedding",
                "index": 0,
                "embedding": [0.1] * 1536
            }
        ],
        "usage": {
            "prompt_tokens": 2,
            "total_tokens": 2
        },
        "_artemis": {
            "provider": "openrouter",
            "dimensions": 1536,
            "latency_ms": 123
        }
    }


@pytest.fixture
def mock_health_response():
    """Standard health check response."""
    return {
        "status": "healthy",
        "service": "artemis",
        "version": "1.0.0"
    }


@pytest.fixture
def mock_embeddings_health_response():
    """Standard embeddings health response."""
    return {
        "status": "healthy",
        "mode": "cloud",
        "ollama": "disabled",
        "providers": ["openrouter", "openai", "voyage"],
        "message": "Using cloud embedding providers"
    }
