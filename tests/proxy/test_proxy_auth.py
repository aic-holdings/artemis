"""Tests for proxy authentication."""
import pytest
import re


class TestProxyAuthentication:
    """Test proxy API key authentication."""

    @pytest.mark.asyncio
    async def test_proxy_requires_api_key(self, client):
        """Proxy endpoint requires an API key."""
        response = await client.post("/v1/openai/chat/completions")
        assert response.status_code == 401
        assert "Authorization" in response.json().get("detail", "")

    @pytest.mark.asyncio
    async def test_proxy_invalid_key_format(self, client):
        """Proxy rejects keys with invalid format."""
        response = await client.post(
            "/v1/openai/chat/completions",
            headers={"Authorization": "Bearer invalid-key-format"},
        )
        assert response.status_code == 401
        assert "Invalid API key" in response.json().get("detail", "")

    @pytest.mark.asyncio
    async def test_proxy_nonexistent_key(self, client, test_db):
        """Proxy rejects nonexistent API keys."""
        response = await client.post(
            "/v1/openai/chat/completions",
            headers={"Authorization": "Bearer art_nonexistent123456789"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_proxy_revoked_key_rejected(self, authenticated_client, test_db):
        """Proxy rejects revoked API keys."""
        # Create a key
        key_response = await authenticated_client.post(
            "/api-keys",
            data={"name": "To Be Revoked"},
            follow_redirects=True,
        )

        # Extract the key
        match = re.search(r'art_[A-Za-z0-9_-]+', key_response.text)
        api_key = match.group(0)

        # Revoke it
        page = await authenticated_client.get("/api-keys")
        revoke_match = re.search(r'/api-keys/([a-f0-9-]+)/revoke', page.text)
        key_id = revoke_match.group(1)
        await authenticated_client.post(f"/api-keys/{key_id}/revoke")

        # Try to use revoked key
        response = await authenticated_client.post(
            "/v1/openai/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 401


class TestProxyProviders:
    """Test proxy provider validation."""

    @pytest.mark.asyncio
    async def test_proxy_invalid_provider(self, client):
        """Proxy rejects invalid provider names."""
        response = await client.post(
            "/v1/invalid_provider/test",
            headers={"Authorization": "Bearer art_test12345678901234567890"},
        )
        # Should fail with 400 or 401
        assert response.status_code in [400, 401]

    @pytest.mark.asyncio
    async def test_proxy_valid_providers(self, client):
        """All valid providers are recognized."""
        valid_providers = ["openai", "anthropic", "google", "perplexity", "openrouter"]

        for provider in valid_providers:
            response = await client.post(
                f"/v1/{provider}/chat/completions",
                headers={"Authorization": "Bearer art_test12345678901234567890"},
            )
            # Should fail with auth, not invalid provider
            assert response.status_code == 401


class TestProxyMissingProviderKey:
    """Test proxy behavior when provider key is not configured."""

    @pytest.mark.asyncio
    async def test_proxy_missing_provider_key(self, authenticated_client, test_db):
        """Proxy returns error when provider key is not configured."""
        # Create an Artemis API key
        key_response = await authenticated_client.post(
            "/api-keys",
            data={"name": "Test Key"},
            follow_redirects=True,
        )

        match = re.search(r'art_[A-Za-z0-9_-]+', key_response.text)
        if match:
            api_key = match.group(0)

            # Try to use without setting up provider key
            response = await authenticated_client.post(
                "/v1/openai/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
            assert response.status_code == 400
            # Error is in OpenAI-compatible format with error.message
            error_data = response.json()
            error_message = error_data.get("error", {}).get("message", "")
            assert "openai" in error_message.lower()
