"""Tests for config commands."""
import pytest
from typer.testing import CliRunner

from artemis_cli.cli import app


class TestConfigInit:
    """Tests for 'artemis config init' command."""

    def test_init_creates_config(self, cli_runner, temp_config):
        """Test config init creates directory and file."""
        result = cli_runner.invoke(app, ["config", "init"])

        assert result.exit_code == 0
        assert "Created" in result.stdout

        # Verify file was created
        config_file = temp_config / "config.yaml"
        assert config_file.exists()

    def test_init_when_exists(self, cli_runner, temp_config):
        """Test config init when config already exists."""
        # Create existing config
        config_file = temp_config / "config.yaml"
        config_file.write_text("url: http://test.com\n")

        result = cli_runner.invoke(app, ["config", "init"])

        assert result.exit_code == 0
        assert "already exists" in result.stdout


class TestConfigSet:
    """Tests for 'artemis config set' command."""

    def test_set_api_key(self, cli_runner, temp_config):
        """Test setting api_key."""
        result = cli_runner.invoke(app, ["config", "set", "api_key", "art_test123"])

        assert result.exit_code == 0
        assert "Set api_key" in result.stdout
        # Key should be masked in output (short keys show ***)
        assert "art_test123" not in result.stdout  # Full key should not appear
        assert ("art_test1..." in result.stdout or "***" in result.stdout)

        # Verify file contents
        config_file = temp_config / "config.yaml"
        content = config_file.read_text()
        assert "api_key: art_test123" in content

    def test_set_url(self, cli_runner, temp_config):
        """Test setting url."""
        result = cli_runner.invoke(
            app,
            ["config", "set", "url", "http://localhost:8767"]
        )

        assert result.exit_code == 0
        assert "Set url" in result.stdout
        # URL should not be masked
        assert "http://localhost:8767" in result.stdout

    def test_set_master_key(self, cli_runner, temp_config):
        """Test setting master_api_key."""
        result = cli_runner.invoke(
            app,
            ["config", "set", "master_api_key", "artemis_master_xyz"]
        )

        assert result.exit_code == 0
        # Key should be masked
        assert "artemis_mast..." in result.stdout


class TestConfigGet:
    """Tests for 'artemis config get' command."""

    def test_get_existing_key(self, cli_runner, temp_config):
        """Test getting an existing config value."""
        # Set up config
        config_file = temp_config / "config.yaml"
        config_file.write_text("url: http://test.com\n")

        result = cli_runner.invoke(app, ["config", "get", "url"])

        assert result.exit_code == 0
        assert "http://test.com" in result.stdout

    def test_get_missing_key(self, cli_runner, temp_config):
        """Test error when key doesn't exist."""
        # Create empty config
        config_file = temp_config / "config.yaml"
        config_file.write_text("")

        result = cli_runner.invoke(app, ["config", "get", "nonexistent"])

        assert result.exit_code == 1
        assert "Key not found" in result.stderr

    def test_get_raw_output(self, cli_runner, temp_config):
        """Test getting raw value without decoration."""
        config_file = temp_config / "config.yaml"
        config_file.write_text("api_key: art_secret123\n")

        result = cli_runner.invoke(app, ["config", "get", "api_key", "--raw"])

        assert result.exit_code == 0
        # Raw output should have the full key
        assert "art_secret123" in result.stdout


class TestConfigShow:
    """Tests for 'artemis config show' command."""

    def test_show_config(self, cli_runner, temp_config):
        """Test showing all config values."""
        config_file = temp_config / "config.yaml"
        config_file.write_text("url: http://test.com\napi_key: art_xyz\n")

        result = cli_runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        assert "http://test.com" in result.stdout
        # Keys should be masked (short keys show ***)
        assert "art_xyz" not in result.stdout  # Full key should not appear
        assert ("art_x..." in result.stdout or "***" in result.stdout)

    def test_show_empty_config(self, cli_runner, temp_config):
        """Test showing when no config exists."""
        result = cli_runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        assert "No config" in result.stdout

    def test_show_json(self, cli_runner, temp_config):
        """Test showing config as JSON."""
        config_file = temp_config / "config.yaml"
        config_file.write_text("url: http://test.com\n")

        result = cli_runner.invoke(app, ["config", "show", "--json"])

        assert result.exit_code == 0
        assert '"url"' in result.stdout


class TestConfigPath:
    """Tests for 'artemis config path' command."""

    def test_show_path(self, cli_runner, temp_config):
        """Test showing config file path."""
        result = cli_runner.invoke(app, ["config", "path"])

        assert result.exit_code == 0
        assert "config.yaml" in result.stdout
