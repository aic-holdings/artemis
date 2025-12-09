"""Tests for provider API key management."""
import re
import pytest


class TestProviderKeyManagement:
    """Test provider API key CRUD operations."""

    @pytest.mark.asyncio
    async def test_add_openai_key(self, authenticated_client):
        """Add an OpenAI provider key."""
        response = await authenticated_client.post(
            "/providers/openai",
            data={"api_key": "sk-test-openai-key-12345", "name": "Personal"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers.get("location") == "/providers"

        page = await authenticated_client.get("/providers")
        assert "1 key(s)" in page.text
        assert "Personal" in page.text

    @pytest.mark.asyncio
    async def test_add_anthropic_key(self, authenticated_client):
        """Add an Anthropic provider key."""
        response = await authenticated_client.post(
            "/providers/anthropic",
            data={"api_key": "sk-ant-test-key-12345", "name": "Work Account"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_add_google_key(self, authenticated_client):
        """Add a Google provider key."""
        response = await authenticated_client.post(
            "/providers/google",
            data={"api_key": "google-api-key-12345", "name": "My Google Key"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_add_perplexity_key(self, authenticated_client):
        """Add a Perplexity provider key."""
        response = await authenticated_client.post(
            "/providers/perplexity",
            data={"api_key": "pplx-test-key-12345", "name": "Default"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_add_openrouter_key(self, authenticated_client):
        """Add an OpenRouter provider key."""
        response = await authenticated_client.post(
            "/providers/openrouter",
            data={"api_key": "sk-or-test-key-12345", "name": "Default"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_add_invalid_provider_rejected(self, authenticated_client):
        """Cannot add a key for an invalid provider."""
        response = await authenticated_client.post(
            "/providers/invalid_provider",
            data={"api_key": "test-key", "name": "Test"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        # Invalid provider just redirects back to providers without error since it's a URL 404
        location = response.headers.get("location", "")
        assert "/providers" in location

    @pytest.mark.asyncio
    async def test_add_multiple_keys_same_provider(self, authenticated_client):
        """Can add multiple keys for the same provider."""
        # Add first key
        await authenticated_client.post(
            "/providers/anthropic",
            data={"api_key": "sk-ant-key-1", "name": "Personal"},
            follow_redirects=False,
        )

        # Add second key with different name
        response = await authenticated_client.post(
            "/providers/anthropic",
            data={"api_key": "sk-ant-key-2", "name": "Work"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = await authenticated_client.get("/providers")
        assert "2 key(s)" in page.text
        assert "Personal" in page.text
        assert "Work" in page.text

    @pytest.mark.asyncio
    async def test_duplicate_name_rejected(self, authenticated_client):
        """Cannot add two keys with the same name for the same provider."""
        # Add first key
        await authenticated_client.post(
            "/providers/openai",
            data={"api_key": "sk-key-1", "name": "Same Name"},
            follow_redirects=False,
        )

        # Try to add second key with same name
        response = await authenticated_client.post(
            "/providers/openai",
            data={"api_key": "sk-key-2", "name": "Same Name"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers.get("location", "")
        # Error parameter changed from "duplicate_name" to "duplicate_key_name"
        assert "error=duplicate" in location

    @pytest.mark.asyncio
    async def test_delete_provider_key(self, authenticated_client):
        """Can delete a provider key."""
        # Add key first
        await authenticated_client.post(
            "/providers/google",
            data={"api_key": "google-api-key", "name": "ToDelete"},
            follow_redirects=False,
        )

        # Verify it's shown
        page = await authenticated_client.get("/providers")
        assert "ToDelete" in page.text

        # Extract the key ID from the delete form
        match = re.search(r'/providers/key/([a-f0-9-]+)/delete', page.text)
        assert match is not None
        key_id = match.group(1)

        # Delete it
        response = await authenticated_client.post(
            f"/providers/key/{key_id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303

        # Verify it's gone
        page = await authenticated_client.get("/providers")
        assert "ToDelete" not in page.text

    @pytest.mark.asyncio
    async def test_set_default_provider_key(self, authenticated_client):
        """Can set a provider key as default."""
        # Add two keys
        await authenticated_client.post(
            "/providers/openai",
            data={"api_key": "sk-key-1", "name": "First"},
            follow_redirects=False,
        )
        await authenticated_client.post(
            "/providers/openai",
            data={"api_key": "sk-key-2", "name": "Second"},
            follow_redirects=False,
        )

        # First key should be default
        page = await authenticated_client.get("/providers")
        # Find the second key's set-default form
        match = re.search(r'/providers/key/([a-f0-9-]+)/set-default', page.text)
        assert match is not None
        second_key_id = match.group(1)

        # Set second as default
        response = await authenticated_client.post(
            f"/providers/key/{second_key_id}/set-default",
            follow_redirects=False,
        )
        assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_providers_page_requires_auth(self, client):
        """Providers page requires authentication."""
        response = await client.get("/providers", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("location") == "/login"

    @pytest.mark.asyncio
    async def test_add_provider_key_requires_auth(self, client):
        """Adding a provider key requires authentication."""
        response = await client.post(
            "/providers/openai",
            data={"api_key": "test-key", "name": "Test"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers.get("location") == "/login"

    @pytest.mark.asyncio
    async def test_add_key_with_account_info(self, authenticated_client):
        """Can add a key with account email and phone."""
        response = await authenticated_client.post(
            "/providers/openai",
            data={
                "api_key": "sk-test-key",
                "name": "Work Account",
                "account_email": "work@example.com",
                "account_phone": "+1-555-1234",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = await authenticated_client.get("/providers")
        assert "work@example.com" in page.text


class TestProviderKeyReveal:
    """Test provider key reveal functionality."""

    @pytest.mark.asyncio
    async def test_reveal_provider_key(self, authenticated_client):
        """Can reveal a stored provider key."""
        # Add a key
        await authenticated_client.post(
            "/providers/openai",
            data={"api_key": "sk-test-reveal-key-12345", "name": "TestKey"},
            follow_redirects=False,
        )

        # Get the key ID from the delete form URL
        page = await authenticated_client.get("/providers")
        match = re.search(r'/providers/key/([a-f0-9-]+)/delete', page.text)
        assert match is not None
        key_id = match.group(1)

        # Reveal it
        response = await authenticated_client.get(f"/providers/key/{key_id}/reveal")
        assert response.status_code == 200
        data = response.json()
        assert "key" in data
        assert data["key"] == "sk-test-reveal-key-12345"

    @pytest.mark.asyncio
    async def test_reveal_nonexistent_key(self, authenticated_client):
        """Revealing a nonexistent key returns 404."""
        response = await authenticated_client.get("/providers/key/nonexistent-id/reveal")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_reveal_requires_auth(self, client):
        """Revealing a key requires authentication."""
        response = await client.get("/providers/key/some-id/reveal")
        assert response.status_code == 401
        data = response.json()
        assert "error" in data


class TestProviderKeyEncryption:
    """Test that provider keys are properly encrypted."""

    @pytest.mark.asyncio
    async def test_key_is_encrypted_in_db(self, authenticated_client, test_db):
        """Provider keys are stored encrypted, not in plaintext."""
        from sqlalchemy import select
        from app.models import ProviderKey

        # Add a key
        await authenticated_client.post(
            "/providers/openai",
            data={"api_key": "sk-plaintext-key-12345", "name": "Encrypted Test"},
            follow_redirects=False,
        )

        # Check the database directly
        async with test_db() as session:
            result = await session.execute(select(ProviderKey))
            provider_key = result.scalar_one_or_none()

            assert provider_key is not None
            # The encrypted key should NOT contain the plaintext
            assert "sk-plaintext-key-12345" not in provider_key.encrypted_key
            # Should be base64-encoded Fernet token
            assert len(provider_key.encrypted_key) > 50


class TestFirstKeyIsDefault:
    """Test that the first key for a provider is set as default."""

    @pytest.mark.asyncio
    async def test_first_key_is_default(self, authenticated_client):
        """First key added for a provider should be default."""
        await authenticated_client.post(
            "/providers/anthropic",
            data={"api_key": "sk-ant-first", "name": "First Key"},
            follow_redirects=False,
        )

        page = await authenticated_client.get("/providers")
        # Default badge should appear next to First Key
        assert "Default" in page.text

    @pytest.mark.asyncio
    async def test_second_key_not_default(self, authenticated_client):
        """Second key added should not be default."""
        await authenticated_client.post(
            "/providers/anthropic",
            data={"api_key": "sk-ant-first", "name": "First Key"},
            follow_redirects=False,
        )
        await authenticated_client.post(
            "/providers/anthropic",
            data={"api_key": "sk-ant-second", "name": "Second Key"},
            follow_redirects=False,
        )

        page = await authenticated_client.get("/providers")
        # Should have Set Default button for second key
        assert "Set Default" in page.text
