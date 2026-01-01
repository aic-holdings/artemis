"""
Provider service - manages the Provider reference table.

Providers are a reference table containing metadata about LLM providers.
These are typically seeded at startup and rarely change.
"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Provider


# Default provider configurations
DEFAULT_PROVIDERS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "docs_url": "https://platform.openai.com/docs",
        "is_active": True,
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com",
        "docs_url": "https://docs.anthropic.com",
        "is_active": True,
    },
    {
        "id": "google",
        "name": "Google",
        "base_url": "https://generativelanguage.googleapis.com",
        "docs_url": "https://ai.google.dev/docs",
        "is_active": True,
    },
    {
        "id": "perplexity",
        "name": "Perplexity",
        "base_url": "https://api.perplexity.ai",
        "docs_url": "https://docs.perplexity.ai",
        "is_active": True,
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "docs_url": "https://openrouter.ai/docs",
        "is_active": True,
    },
    {
        "id": "v0",
        "name": "v0 (Vercel)",
        "base_url": "https://api.v0.dev/v1",
        "docs_url": "https://v0.app/docs/api/model",
        "is_active": True,
    },
]


class ProviderService:
    """Service for managing LLM providers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, provider_id: str) -> Optional[Provider]:
        """Get a provider by its ID (slug)."""
        result = await self.db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        return result.scalar_one_or_none()

    async def get_all(self, active_only: bool = True) -> list[Provider]:
        """Get all providers, optionally filtering to active only."""
        query = select(Provider).order_by(Provider.name)
        if active_only:
            query = query.where(Provider.is_active == True)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        provider_id: str,
        name: str,
        base_url: Optional[str] = None,
        docs_url: Optional[str] = None,
        is_active: bool = True,
    ) -> Provider:
        """Create a new provider."""
        provider = Provider(
            id=provider_id.lower(),
            name=name,
            base_url=base_url,
            docs_url=docs_url,
            is_active=is_active,
        )
        self.db.add(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        return provider

    async def update(
        self,
        provider_id: str,
        name: Optional[str] = None,
        base_url: Optional[str] = None,
        docs_url: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Provider]:
        """Update a provider's metadata."""
        provider = await self.get_by_id(provider_id)
        if not provider:
            return None

        if name is not None:
            provider.name = name
        if base_url is not None:
            provider.base_url = base_url
        if docs_url is not None:
            provider.docs_url = docs_url
        if is_active is not None:
            provider.is_active = is_active

        await self.db.commit()
        return provider

    async def seed_defaults(self) -> list[Provider]:
        """Seed the default providers if they don't exist."""
        created = []
        for config in DEFAULT_PROVIDERS:
            existing = await self.get_by_id(config["id"])
            if not existing:
                provider = await self.create(
                    provider_id=config["id"],
                    name=config["name"],
                    base_url=config.get("base_url"),
                    docs_url=config.get("docs_url"),
                    is_active=config.get("is_active", True),
                )
                created.append(provider)
        return created
