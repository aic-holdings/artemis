"""Tests for Venus (v0) provider integration."""
import pytest

from app.config import settings
from app.providers.models import PROVIDER_MODELS, PROVIDER_NAMES
from app.providers.pricing import FALLBACK_PRICING


class TestVenusProviderConfig:
    """Test Venus/v0 is properly configured."""

    def test_v0_in_provider_urls(self):
        """v0 should be in PROVIDER_URLS."""
        assert "v0" in settings.PROVIDER_URLS
        assert settings.PROVIDER_URLS["v0"] == "https://api.v0.dev/v1"

    def test_v0_in_provider_models(self):
        """v0 should have models defined."""
        assert "v0" in PROVIDER_MODELS
        models = PROVIDER_MODELS["v0"]
        assert len(models) >= 2

        model_ids = [m[0] for m in models]
        assert "v0-1.5-md" in model_ids
        assert "v0-1.5-lg" in model_ids

    def test_v0_in_provider_names(self):
        """v0 should have a display name."""
        assert "v0" in PROVIDER_NAMES
        assert PROVIDER_NAMES["v0"] == "v0 (Vercel)"

    def test_v0_in_fallback_pricing(self):
        """v0 should have fallback pricing."""
        assert "v0" in FALLBACK_PRICING
        assert "v0-1.5-md" in FALLBACK_PRICING["v0"]
        assert "v0-1.5-lg" in FALLBACK_PRICING["v0"]


class TestVenusProviderSeeding:
    """Test Venus/v0 is seeded correctly."""

    def test_v0_in_default_providers(self):
        """v0 should be in DEFAULT_PROVIDERS for auto-seeding."""
        from app.services.provider_service import DEFAULT_PROVIDERS

        provider_ids = [p["id"] for p in DEFAULT_PROVIDERS]
        assert "v0" in provider_ids

        v0_config = next(p for p in DEFAULT_PROVIDERS if p["id"] == "v0")
        assert v0_config["name"] == "v0 (Vercel)"
        assert v0_config["base_url"] == "https://api.v0.dev/v1"
        assert v0_config["docs_url"] == "https://v0.app/docs/api/model"
        assert v0_config["is_active"] is True


class TestVenusProxy:
    """Test Venus/v0 proxy routing."""

    @pytest.mark.asyncio
    async def test_v0_provider_recognized(self, client):
        """v0 provider should be recognized in proxy routes."""
        response = await client.post(
            "/v1/v0/chat/completions",
            headers={"Authorization": "Bearer art_test12345678901234567890"},
        )
        # Should fail with auth error, not "invalid provider"
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_v0_requires_provider_key(self, authenticated_client, test_db):
        """v0 requests should require a configured provider key."""
        import re

        # Create an Artemis API key
        key_response = await authenticated_client.post(
            "/api-keys",
            data={"name": "Venus Test Key"},
            follow_redirects=True,
        )

        match = re.search(r'art_[A-Za-z0-9_-]+', key_response.text)
        if match:
            api_key = match.group(0)

            # Try to use without setting up v0 provider key
            response = await authenticated_client.post(
                "/v1/v0/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "v0-1.5-md",
                    "messages": [{"role": "user", "content": "Create a button"}],
                },
            )
            assert response.status_code == 400
            error_data = response.json()
            error_message = error_data.get("error", {}).get("message", "")
            assert "v0" in error_message.lower()


class TestVenusModels:
    """Test Venus model specifications."""

    def test_v0_model_specs(self):
        """v0 models should have correct specifications."""
        models = PROVIDER_MODELS["v0"]

        # Check v0-1.5-md
        md_model = next((m for m in models if m[0] == "v0-1.5-md"), None)
        assert md_model is not None
        assert md_model[1] == "v0 1.5 Medium"

        # Check v0-1.5-lg
        lg_model = next((m for m in models if m[0] == "v0-1.5-lg"), None)
        assert lg_model is not None
        assert lg_model[1] == "v0 1.5 Large"
