"""
Provider model service for managing available models.

Supports fetching models from provider APIs (like OpenRouter) and managing
which models are enabled for use in the Artemis instance.
"""
import httpx
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProviderModel, Provider


# Provider API endpoints for fetching models
PROVIDER_MODEL_APIS = {
    "openrouter": "https://openrouter.ai/api/v1/models",
}

# Map OpenRouter model prefixes to our provider IDs
# NOTE: For OpenRouter sync, we keep ALL models under "openrouter" provider
# This mapping could be used in the future for direct provider model syncing
OPENROUTER_PREFIX_TO_PROVIDER = {
    "openai/": "openrouter",
    "anthropic/": "openrouter",
    "google/": "openrouter",
    "perplexity/": "openrouter",
    "meta-llama/": "openrouter",
    "mistralai/": "openrouter",
    "deepseek/": "openrouter",
    "qwen/": "openrouter",
    "cohere/": "openrouter",
}


class ProviderModelService:
    """Service for managing provider models."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_for_provider(
        self, provider_id: str, enabled_only: bool = False
    ) -> list[ProviderModel]:
        """Get all models for a provider."""
        query = select(ProviderModel).where(ProviderModel.provider_id == provider_id)
        if enabled_only:
            query = query.where(ProviderModel.is_enabled == True)
        query = query.order_by(ProviderModel.name)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_enabled_models(self, provider_ids: list[str] | None = None) -> list[ProviderModel]:
        """Get all enabled models, optionally filtered by providers."""
        query = select(ProviderModel).where(ProviderModel.is_enabled == True)
        if provider_ids:
            query = query.where(ProviderModel.provider_id.in_(provider_ids))
        query = query.order_by(ProviderModel.provider_id, ProviderModel.name)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def toggle_model(self, model_id: str, enabled: bool) -> ProviderModel | None:
        """Toggle a model's enabled state."""
        result = await self.db.execute(
            select(ProviderModel).where(ProviderModel.id == model_id)
        )
        model = result.scalar_one_or_none()
        if model:
            model.is_enabled = enabled
            await self.db.commit()
        return model

    async def sync_openrouter_models(self, api_key: str | None = None) -> dict:
        """
        Fetch and sync models from OpenRouter API.

        Args:
            api_key: Optional OpenRouter API key for authenticated requests

        Returns:
            Dict with sync stats: {"added": int, "updated": int, "total": int}
        """
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                PROVIDER_MODEL_APIS["openrouter"],
                headers=headers,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

        models_data = data.get("data", [])
        added = 0
        updated = 0

        # Verify openrouter provider exists
        provider_result = await self.db.execute(
            select(Provider).where(Provider.id == "openrouter")
        )
        if not provider_result.scalar_one_or_none():
            raise ValueError("OpenRouter provider not found in database")

        for model_data in models_data:
            model_id = model_data.get("id", "")
            if not model_id:
                continue

            # All OpenRouter models go under the openrouter provider
            provider_id = "openrouter"

            # Extract pricing (convert from per-token to per-1M tokens in cents)
            pricing = model_data.get("pricing", {})
            input_price = None
            output_price = None
            if pricing:
                # OpenRouter prices are strings in dollars per token
                try:
                    prompt_price = float(pricing.get("prompt", 0))
                    completion_price = float(pricing.get("completion", 0))
                    # Convert: $/token -> cents/1M tokens
                    # $0.000001/token = $1/1M tokens = 100 cents/1M tokens
                    input_price = prompt_price * 1_000_000 * 100
                    output_price = completion_price * 1_000_000 * 100
                except (ValueError, TypeError):
                    pass

            # Check if model already exists
            existing = await self.db.execute(
                select(ProviderModel).where(
                    ProviderModel.provider_id == provider_id,
                    ProviderModel.model_id == model_id,
                )
            )
            existing_model = existing.scalar_one_or_none()

            if existing_model:
                # Update existing model
                existing_model.name = model_data.get("name", model_id)
                existing_model.description = model_data.get("description")
                existing_model.context_length = model_data.get("context_length")
                existing_model.max_completion_tokens = (
                    model_data.get("top_provider", {}).get("max_completion_tokens")
                )
                existing_model.input_price_per_1m = input_price
                existing_model.output_price_per_1m = output_price
                existing_model.architecture = model_data.get("architecture")
                existing_model.raw_data = model_data
                existing_model.last_synced_at = datetime.now(timezone.utc)
                updated += 1
            else:
                # Create new model
                new_model = ProviderModel(
                    provider_id=provider_id,
                    model_id=model_id,
                    name=model_data.get("name", model_id),
                    description=model_data.get("description"),
                    context_length=model_data.get("context_length"),
                    max_completion_tokens=model_data.get("top_provider", {}).get(
                        "max_completion_tokens"
                    ),
                    input_price_per_1m=input_price,
                    output_price_per_1m=output_price,
                    is_enabled=False,  # Disabled by default, user enables what they want
                    architecture=model_data.get("architecture"),
                    raw_data=model_data,
                    last_synced_at=datetime.now(timezone.utc),
                )
                self.db.add(new_model)
                added += 1

        await self.db.commit()

        return {
            "added": added,
            "updated": updated,
            "total": len(models_data),
        }

    async def get_model_count_by_provider(self) -> dict[str, dict]:
        """Get model counts per provider."""
        result = await self.db.execute(
            select(ProviderModel.provider_id, ProviderModel.is_enabled)
        )
        rows = result.all()

        counts: dict[str, dict] = {}
        for provider_id, is_enabled in rows:
            if provider_id not in counts:
                counts[provider_id] = {"total": 0, "enabled": 0}
            counts[provider_id]["total"] += 1
            if is_enabled:
                counts[provider_id]["enabled"] += 1

        return counts

    def _normalize_model_id(self, model_id: str) -> str:
        """
        Normalize a model ID by stripping OpenRouter variant suffixes.

        OpenRouter supports variants like:
        - :online - Web search enabled
        - :thinking - Extended thinking/reasoning
        - :extended - Extended context

        These can be stacked (e.g., openai/gpt-4o:online:thinking).
        We strip all suffixes to get the base model for validation.
        """
        # Known OpenRouter variant suffixes
        variant_suffixes = [":online", ":thinking", ":extended", ":free", ":beta"]

        normalized = model_id
        for suffix in variant_suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]

        # Handle stacked suffixes by recursing
        if normalized != model_id:
            return self._normalize_model_id(normalized)

        return normalized

    async def is_model_enabled(self, provider_id: str, model_id: str) -> bool:
        """
        Check if a specific model is enabled for use.

        Returns True if:
        - The model exists in the database AND is enabled
        - OR the model doesn't exist in the database (allow unknown models for flexibility)

        Returns False if:
        - The model exists in the database AND is disabled

        Note: Model variants (e.g., :online, :thinking) are normalized to the base
        model for validation. So if openai/gpt-4o is disabled, openai/gpt-4o:online
        is also disabled.
        """
        # Normalize model ID to strip variant suffixes
        base_model_id = self._normalize_model_id(model_id)

        result = await self.db.execute(
            select(ProviderModel).where(
                ProviderModel.provider_id == provider_id,
                ProviderModel.model_id == base_model_id,
            )
        )
        model = result.scalar_one_or_none()

        if model is None:
            # Model not in our database - allow it (for new models, direct provider access)
            return True

        return model.is_enabled

    async def get_model_if_enabled(self, provider_id: str, model_id: str) -> ProviderModel | None:
        """
        Get a model if it exists and is enabled.

        Returns:
        - ProviderModel if model exists and is enabled
        - None if model doesn't exist OR exists but is disabled
        """
        result = await self.db.execute(
            select(ProviderModel).where(
                ProviderModel.provider_id == provider_id,
                ProviderModel.model_id == model_id,
                ProviderModel.is_enabled == True,
            )
        )
        return result.scalar_one_or_none()
