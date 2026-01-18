"""Tests for health and version commands."""
import json
import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from artemis_cli.cli import app


class TestHealth:
    """Tests for 'artemis health' command."""

    def test_health_healthy(self, cli_runner, env_url, mock_health_response):
        """Test healthy service response."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_health_response).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("artemis_cli.cli.urlopen", return_value=mock_response):
            result = cli_runner.invoke(app, ["health"])

        assert result.exit_code == 0
        assert "healthy" in result.stdout
        assert "artemis" in result.stdout

    def test_health_verbose(self, cli_runner, env_url, mock_health_response):
        """Test verbose health output."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_health_response).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("artemis_cli.cli.urlopen", return_value=mock_response):
            result = cli_runner.invoke(app, ["health", "--verbose"])

        assert result.exit_code == 0
        assert '"status"' in result.stdout

    def test_health_unhealthy(self, cli_runner, env_url):
        """Test unhealthy service response."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "unhealthy",
            "service": "artemis",
            "version": "1.0.0"
        }).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("artemis_cli.cli.urlopen", return_value=mock_response):
            result = cli_runner.invoke(app, ["health"])

        assert result.exit_code == 0
        assert "unhealthy" in result.stdout

    def test_health_connection_error(self, cli_runner, env_url):
        """Test connection error handling."""
        from urllib.error import URLError

        with patch("artemis_cli.cli.urlopen", side_effect=URLError("Connection refused")):
            result = cli_runner.invoke(app, ["health"])

        assert result.exit_code == 1
        assert "Error" in result.stderr


class TestVersion:
    """Tests for 'artemis version' command."""

    def test_version(self, cli_runner):
        """Test version output."""
        result = cli_runner.invoke(app, ["version"])

        assert result.exit_code == 0
        assert "artemis-cli" in result.stdout
        assert "v2.0.0" in result.stdout
        assert "Typer" in result.stdout


class TestHelp:
    """Tests for help output."""

    def test_main_help(self, cli_runner):
        """Test main help output."""
        result = cli_runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "admin" in result.stdout
        assert "embeddings" in result.stdout
        assert "config" in result.stdout
        assert "health" in result.stdout

    def test_admin_help(self, cli_runner):
        """Test admin subcommand help."""
        result = cli_runner.invoke(app, ["admin", "--help"])

        assert result.exit_code == 0
        assert "create-account" in result.stdout
        assert "list-accounts" in result.stdout
        assert "issue-key" in result.stdout

    def test_config_help(self, cli_runner):
        """Test config subcommand help."""
        result = cli_runner.invoke(app, ["config", "--help"])

        assert result.exit_code == 0
        assert "init" in result.stdout
        assert "set" in result.stdout
        assert "get" in result.stdout
        assert "show" in result.stdout

    def test_embeddings_help(self, cli_runner):
        """Test embeddings subcommand help."""
        result = cli_runner.invoke(app, ["embeddings", "--help"])

        assert result.exit_code == 0
        assert "health" in result.stdout
        assert "test" in result.stdout
        assert "providers" in result.stdout
