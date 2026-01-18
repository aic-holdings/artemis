"""Tests for admin commands."""
import pytest
from typer.testing import CliRunner

from artemis_cli.cli import app


class TestAdminCreateAccount:
    """Tests for 'artemis admin create-account' command."""

    def test_create_account_success(
        self, cli_runner, mock_api, env_master_key, mock_service_account_response
    ):
        """Test successful service account creation."""
        mock_api.return_value = mock_service_account_response

        result = cli_runner.invoke(app, ["admin", "create-account", "test-service"])

        assert result.exit_code == 0
        assert "Created service account: test-service" in result.stdout
        assert "art_test_generated_key_abc123" in result.stdout
        mock_api.assert_called_once()

    def test_create_account_with_description(
        self, cli_runner, mock_api, env_master_key, mock_service_account_response
    ):
        """Test service account creation with description."""
        mock_api.return_value = mock_service_account_response

        result = cli_runner.invoke(
            app,
            ["admin", "create-account", "test-service", "-d", "My test service"]
        )

        assert result.exit_code == 0
        call_args = mock_api.call_args
        assert call_args[0][2]["description"] == "My test service"

    def test_create_account_missing_master_key(self, cli_runner, clean_env, temp_config):
        """Test error when MASTER_API_KEY is not set."""
        result = cli_runner.invoke(app, ["admin", "create-account", "test"])

        assert result.exit_code == 1
        assert "MASTER_API_KEY" in result.stderr


class TestAdminListAccounts:
    """Tests for 'artemis admin list-accounts' command."""

    def test_list_accounts_success(
        self, cli_runner, mock_api, env_master_key, mock_accounts_list_response
    ):
        """Test listing service accounts."""
        mock_api.return_value = mock_accounts_list_response

        result = cli_runner.invoke(app, ["admin", "list-accounts"])

        assert result.exit_code == 0
        assert "service-one" in result.stdout
        assert "service-two" in result.stdout

    def test_list_accounts_json(
        self, cli_runner, mock_api, env_master_key, mock_accounts_list_response
    ):
        """Test listing accounts with JSON output."""
        mock_api.return_value = mock_accounts_list_response

        result = cli_runner.invoke(app, ["admin", "list-accounts", "--json"])

        assert result.exit_code == 0
        assert '"service_accounts"' in result.stdout

    def test_list_accounts_empty(self, cli_runner, mock_api, env_master_key):
        """Test listing when no accounts exist."""
        mock_api.return_value = {"service_accounts": []}

        result = cli_runner.invoke(app, ["admin", "list-accounts"])

        assert result.exit_code == 0
        assert "No service accounts found" in result.stdout


class TestAdminIssueKey:
    """Tests for 'artemis admin issue-key' command."""

    def test_issue_key_success(self, cli_runner, mock_api, env_master_key):
        """Test issuing a new API key."""
        mock_api.return_value = {
            "api_key": {
                "id": "key-new",
                "key": "art_new_key_xyz",
                "key_prefix": "art_new_key"
            }
        }

        result = cli_runner.invoke(app, ["admin", "issue-key", "test-service"])

        assert result.exit_code == 0
        assert "Issued key" in result.stdout
        assert "art_new_key_xyz" in result.stdout

    def test_issue_key_with_name(self, cli_runner, mock_api, env_master_key):
        """Test issuing a key with custom name."""
        mock_api.return_value = {
            "api_key": {
                "id": "key-prod",
                "key": "art_prod_key_xyz",
                "key_prefix": "art_prod_key"
            }
        }

        result = cli_runner.invoke(
            app,
            ["admin", "issue-key", "test-service", "--name", "production"]
        )

        assert result.exit_code == 0
        call_args = mock_api.call_args
        assert call_args[0][2]["name"] == "production"


class TestAdminListKeys:
    """Tests for 'artemis admin list-keys' command."""

    def test_list_keys_success(self, cli_runner, mock_api, env_master_key):
        """Test listing keys for an account."""
        mock_api.return_value = {
            "api_keys": [
                {
                    "name": "default",
                    "key_prefix": "art_abc123",
                    "revoked_at": None,
                    "last_used_at": "2024-01-15T10:00:00Z"
                },
                {
                    "name": "production",
                    "key_prefix": "art_xyz789",
                    "revoked_at": "2024-01-10T00:00:00Z",
                    "last_used_at": None
                }
            ]
        }

        result = cli_runner.invoke(app, ["admin", "list-keys", "test-service"])

        assert result.exit_code == 0
        assert "default" in result.stdout
        assert "production" in result.stdout
        assert "Active" in result.stdout
        assert "Revoked" in result.stdout


class TestAdminAddProvider:
    """Tests for 'artemis admin add-provider' command."""

    def test_add_provider_success(self, cli_runner, mock_api, env_master_key):
        """Test adding a provider key."""
        mock_api.return_value = {
            "provider_key": {
                "id": "pk-123",
                "provider_id": "openrouter"
            }
        }

        result = cli_runner.invoke(
            app,
            ["admin", "add-provider", "openrouter", "--key", "sk-or-v1-xxx"]
        )

        assert result.exit_code == 0
        assert "Added provider: openrouter" in result.stdout
        assert "****-xxx" in result.stdout  # Masked key suffix


class TestAdminListProviders:
    """Tests for 'artemis admin list-providers' command."""

    def test_list_providers_success(self, cli_runner, mock_api, env_master_key):
        """Test listing provider keys."""
        mock_api.return_value = {
            "provider_keys": [
                {
                    "provider_id": "openrouter",
                    "name": "Default",
                    "key_suffix": "xxx1",
                    "group_name": "Default",
                    "is_active": True,
                    "is_default": True
                },
                {
                    "provider_id": "openai",
                    "name": "Backup",
                    "key_suffix": "xxx2",
                    "group_name": "Default",
                    "is_active": False,
                    "is_default": False
                }
            ]
        }

        result = cli_runner.invoke(app, ["admin", "list-providers"])

        assert result.exit_code == 0
        assert "openrouter" in result.stdout
        assert "openai" in result.stdout
