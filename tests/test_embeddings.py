"""Tests for embeddings commands."""
import json
import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from artemis_cli.cli import app


class TestEmbeddingsHealth:
    """Tests for 'artemis embeddings health' command."""

    def test_health_healthy(
        self, cli_runner, env_url, mock_embeddings_health_response
    ):
        """Test healthy embeddings service."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            mock_embeddings_health_response
        ).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("artemis_cli.cli.urlopen", return_value=mock_response):
            result = cli_runner.invoke(app, ["embeddings", "health"])

        assert result.exit_code == 0
        assert "healthy" in result.stdout
        assert "cloud" in result.stdout

    def test_health_degraded(self, cli_runner, env_url):
        """Test degraded embeddings service."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "degraded",
            "ollama": "unavailable",
            "message": "Ollama not responding"
        }).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("artemis_cli.cli.urlopen", return_value=mock_response):
            result = cli_runner.invoke(app, ["embeddings", "health"])

        assert result.exit_code == 0
        assert "degraded" in result.stdout


class TestEmbeddingsTest:
    """Tests for 'artemis embeddings test' command."""

    def test_embed_text_success(
        self, cli_runner, mock_api, env_api_key, mock_embedding_response
    ):
        """Test successful embedding generation."""
        mock_api.return_value = mock_embedding_response

        result = cli_runner.invoke(app, ["embeddings", "test", "Hello world"])

        assert result.exit_code == 0
        assert "Embedding generated" in result.stdout
        assert "1536" in result.stdout  # dimensions
        assert "openrouter" in result.stdout  # provider

    def test_embed_text_verbose(
        self, cli_runner, mock_api, env_api_key, mock_embedding_response
    ):
        """Test embedding with verbose output."""
        mock_api.return_value = mock_embedding_response

        result = cli_runner.invoke(
            app,
            ["embeddings", "test", "Hello world", "--verbose"]
        )

        assert result.exit_code == 0
        assert "First 5" in result.stdout
        assert "Last 5" in result.stdout

    def test_embed_missing_api_key(self, cli_runner, clean_env, temp_config):
        """Test error when API key not configured."""
        result = cli_runner.invoke(app, ["embeddings", "test", "Hello"])

        assert result.exit_code == 1
        assert "ARTEMIS_API_KEY" in result.stderr


class TestEmbeddingsProviders:
    """Tests for 'artemis embeddings providers' command."""

    def test_list_providers(self, cli_runner, mock_api, env_api_key):
        """Test listing embedding providers."""
        mock_api.return_value = {
            "providers": [
                {
                    "id": "openrouter",
                    "model": "text-embedding-3-small",
                    "dimensions": 1536,
                    "has_key": True
                },
                {
                    "id": "openai",
                    "model": "text-embedding-3-small",
                    "dimensions": 1536,
                    "has_key": False
                }
            ],
            "fallback_order": ["openrouter", "openai", "voyage"]
        }

        result = cli_runner.invoke(app, ["embeddings", "providers"])

        assert result.exit_code == 0
        assert "openrouter" in result.stdout
        assert "openai" in result.stdout
        assert "Fallback" in result.stdout

    def test_list_providers_json(self, cli_runner, mock_api, env_api_key):
        """Test listing providers as JSON."""
        mock_api.return_value = {
            "providers": [{"id": "openrouter", "has_key": True}],
            "fallback_order": ["openrouter"]
        }

        result = cli_runner.invoke(app, ["embeddings", "providers", "--json"])

        assert result.exit_code == 0
        assert '"providers"' in result.stdout
