"""
Demo data service - creates sample organizations, keys, and usage data.
Uses async database access for integration with FastAPI routes.
"""
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Organization, User, Group, GroupMember, APIKey, Provider,
    ProviderAccount, ProviderKey, ModelPricing, UsageLog
)
from app.auth import generate_api_key, encrypt_api_key


# Demo organization name
DEMO_ORG_NAME = "Demo Organization"

# API key names
API_KEY_NAMES = ["Production", "Development", "Staging", "CI/CD"]

# Provider accounts to create
PROVIDER_ACCOUNTS = {
    "openai": [
        {"name": "Personal", "email": "personal@example.com", "phone": "+1-555-0101"},
        {"name": "Work", "email": "work@example.com", "phone": "+1-555-0102"},
    ],
    "anthropic": [
        {"name": "Main Account", "email": "main@example.com", "phone": None},
        {"name": "Research", "email": "research@example.com", "phone": None},
    ],
    "google": [
        {"name": "GCP Project 1", "email": "gcp1@example.com", "phone": None},
    ],
    "perplexity": [
        {"name": "Default", "email": "pplx@example.com", "phone": None},
    ],
    "openrouter": [
        {"name": "OpenRouter Main", "email": "or@example.com", "phone": None},
    ],
}

# Default provider configurations
DEFAULT_PROVIDERS = [
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "docs_url": "https://platform.openai.com/docs"},
    {"id": "anthropic", "name": "Anthropic", "base_url": "https://api.anthropic.com", "docs_url": "https://docs.anthropic.com"},
    {"id": "google", "name": "Google", "base_url": "https://generativelanguage.googleapis.com", "docs_url": "https://ai.google.dev/docs"},
    {"id": "perplexity", "name": "Perplexity", "base_url": "https://api.perplexity.ai", "docs_url": "https://docs.perplexity.ai"},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "docs_url": "https://openrouter.ai/docs"},
]

# Models and their typical token counts (avg_input, avg_output)
MODEL_DATA = {
    "openai": [
        ("gpt-4o", 500, 1500),
        ("gpt-4o-mini", 800, 2000),
        ("gpt-4-turbo", 400, 1200),
        ("o1-mini", 300, 800),
    ],
    "anthropic": [
        ("claude-3-5-sonnet-20241022", 600, 1800),
        ("claude-3-opus-20240229", 400, 1200),
        ("claude-3-haiku-20240307", 1000, 3000),
    ],
    "google": [
        ("gemini-1.5-pro", 500, 1500),
        ("gemini-1.5-flash", 800, 2500),
    ],
    "perplexity": [
        ("llama-3.1-sonar-large-128k-online", 400, 1200),
        ("llama-3.1-sonar-small-128k-online", 600, 1800),
    ],
    "openrouter": [
        ("anthropic/claude-3.5-sonnet", 500, 1500),
        ("openai/gpt-4o", 500, 1500),
        ("meta-llama/llama-3.1-70b-instruct", 700, 2000),
    ],
}

APP_IDS = ["chatbot", "code-assistant", "data-pipeline", "customer-support", None]
USER_IDS = ["user-123", "user-456", "user-789", None]

# Pricing data for seeding (per 1M tokens in cents)
PRICING_HISTORY = {
    "openai": {
        "gpt-4o": {
            "2024-01-01": {"input": 500, "output": 1500, "cache_read_mult": 0.5},
            "2024-06-01": {"input": 250, "output": 1000, "cache_read_mult": 0.5},
        },
        "gpt-4o-mini": {
            "2024-07-01": {"input": 15, "output": 60, "cache_read_mult": 0.5},
        },
        "gpt-4-turbo": {
            "2024-01-01": {"input": 1000, "output": 3000, "cache_read_mult": 0.5},
        },
        "o1-mini": {
            "2024-09-01": {"input": 300, "output": 1200, "reasoning": 1200, "cache_read_mult": 0.5},
        },
    },
    "anthropic": {
        "claude-3-5-sonnet-20241022": {
            "2024-10-22": {"input": 300, "output": 1500, "cache_read_mult": 0.1, "cache_write_mult": 1.25},
        },
        "claude-3-opus-20240229": {
            "2024-02-29": {"input": 1500, "output": 7500, "cache_read_mult": 0.1, "cache_write_mult": 1.25},
        },
        "claude-3-haiku-20240307": {
            "2024-03-07": {"input": 25, "output": 125, "cache_read_mult": 0.1, "cache_write_mult": 1.25},
        },
    },
    "google": {
        "gemini-1.5-pro": {
            "2024-05-01": {"input": 125, "output": 500, "cache_read_mult": 0.25},
        },
        "gemini-1.5-flash": {
            "2024-05-01": {"input": 7.5, "output": 30, "cache_read_mult": 0.25},
        },
    },
    "perplexity": {
        "llama-3.1-sonar-small-128k-online": {
            "2024-01-01": {"input": 20, "output": 20},
        },
        "llama-3.1-sonar-large-128k-online": {
            "2024-01-01": {"input": 100, "output": 100},
        },
    },
    "openrouter": {
        "anthropic/claude-3.5-sonnet": {
            "2024-01-01": {"input": 320, "output": 1600},
        },
        "openai/gpt-4o": {
            "2024-01-01": {"input": 270, "output": 1100},
        },
        "meta-llama/llama-3.1-70b-instruct": {
            "2024-01-01": {"input": 52, "output": 75},
        },
    },
}


async def load_demo_data(user: User, db: AsyncSession) -> dict:
    """
    Load demo data for the given user.
    Creates Demo Organization, groups, API keys, provider keys, and usage logs.
    Returns a summary of what was created.
    """
    summary = {
        "organization": None,
        "group": None,
        "api_keys": 0,
        "providers": 0,
        "provider_accounts": 0,
        "provider_keys": 0,
        "pricing_entries": 0,
        "usage_logs": 0,
    }

    # 1. Create or get Demo Organization
    result = await db.execute(
        select(Organization).where(Organization.name == DEMO_ORG_NAME)
    )
    demo_org = result.scalar_one_or_none()

    if not demo_org:
        demo_org = Organization(name=DEMO_ORG_NAME, owner_id=user.id)
        db.add(demo_org)
        await db.flush()
        summary["organization"] = DEMO_ORG_NAME
    else:
        # Update owner if not set
        if not demo_org.owner_id:
            demo_org.owner_id = user.id
            await db.flush()

    # 2. Create default group for Demo Organization
    result = await db.execute(
        select(Group).where(
            Group.organization_id == demo_org.id,
            Group.is_default == True
        )
    )
    demo_group = result.scalar_one_or_none()

    if not demo_group:
        demo_group = Group(
            organization_id=demo_org.id,
            name="Default",
            description="Default group for all organization members",
            is_default=True,
            created_by_id=user.id
        )
        db.add(demo_group)
        await db.flush()
        summary["group"] = "Default"

    # 3. Add user as owner of the group
    result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == demo_group.id,
            GroupMember.user_id == user.id
        )
    )
    membership = result.scalar_one_or_none()

    if not membership:
        membership = GroupMember(
            group_id=demo_group.id,
            user_id=user.id,
            role="owner"
        )
        db.add(membership)
        await db.flush()

    # 4. Seed providers
    for config in DEFAULT_PROVIDERS:
        result = await db.execute(
            select(Provider).where(Provider.id == config["id"])
        )
        existing = result.scalar_one_or_none()
        if not existing:
            provider = Provider(
                id=config["id"],
                name=config["name"],
                base_url=config.get("base_url"),
                docs_url=config.get("docs_url"),
                is_active=True,
            )
            db.add(provider)
            summary["providers"] += 1
    await db.flush()

    # 5. Create API keys
    api_key_ids = []
    for name in API_KEY_NAMES:
        result = await db.execute(
            select(APIKey).where(
                APIKey.group_id == demo_group.id,
                APIKey.name == name
            )
        )
        existing = result.scalar_one_or_none()

        if not existing:
            full_key, key_hash, key_prefix = generate_api_key()
            api_key = APIKey(
                group_id=demo_group.id,
                user_id=user.id,
                key_hash=key_hash,
                key_prefix=key_prefix,
                encrypted_key=encrypt_api_key(full_key),
                name=name,
            )
            db.add(api_key)
            await db.flush()
            api_key_ids.append(api_key.id)
            summary["api_keys"] += 1
        else:
            api_key_ids.append(existing.id)

    # 6. Create provider accounts and keys
    provider_key_ids = {}
    for provider_id, accounts in PROVIDER_ACCOUNTS.items():
        provider_key_ids[provider_id] = []
        is_first_key = True

        for account_data in accounts:
            result = await db.execute(
                select(ProviderAccount).where(
                    ProviderAccount.group_id == demo_group.id,
                    ProviderAccount.provider_id == provider_id,
                    ProviderAccount.name == account_data["name"]
                )
            )
            account = result.scalar_one_or_none()

            if not account:
                account = ProviderAccount(
                    group_id=demo_group.id,
                    provider_id=provider_id,
                    name=account_data["name"],
                    account_email=account_data.get("email"),
                    account_phone=account_data.get("phone"),
                    created_by_id=user.id,
                    is_active=True,
                )
                db.add(account)
                await db.flush()
                summary["provider_accounts"] += 1

            # Check for existing key
            result = await db.execute(
                select(ProviderKey).where(
                    ProviderKey.provider_account_id == account.id,
                    ProviderKey.name == "Default Key"
                )
            )
            provider_key = result.scalar_one_or_none()

            if not provider_key:
                fake_key = f"sk-fake-{provider_id}-{account_data['name'].lower().replace(' ', '-')}-12345"
                provider_key = ProviderKey(
                    provider_account_id=account.id,
                    user_id=user.id,
                    encrypted_key=encrypt_api_key(fake_key),
                    name="Default Key",
                    key_suffix=fake_key[-4:],
                    is_default=is_first_key,
                    is_active=True,
                )
                db.add(provider_key)
                await db.flush()
                summary["provider_keys"] += 1

            provider_key_ids[provider_id].append(provider_key.id)
            is_first_key = False

    # 7. Seed pricing history
    for provider, models in PRICING_HISTORY.items():
        for model, date_pricing in models.items():
            for date_str, pricing in date_pricing.items():
                effective_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                result = await db.execute(
                    select(ModelPricing).where(
                        ModelPricing.provider == provider,
                        ModelPricing.model == model,
                        ModelPricing.effective_date == effective_date
                    )
                )
                existing = result.scalar_one_or_none()

                if not existing:
                    mp = ModelPricing(
                        provider=provider,
                        model=model,
                        effective_date=effective_date,
                        input_price_per_1m=pricing.get("input", 0),
                        output_price_per_1m=pricing.get("output", 0),
                        cache_read_multiplier=pricing.get("cache_read_mult"),
                        cache_write_multiplier=pricing.get("cache_write_mult"),
                        reasoning_price_per_1m=pricing.get("reasoning"),
                        batch_discount=pricing.get("batch_discount", 0.5),
                        notes="Seeded from demo data"
                    )
                    db.add(mp)
                    summary["pricing_entries"] += 1

    await db.flush()

    # 8. Create usage logs (30 days, ~30 requests/day for quick loading)
    now = datetime.now(timezone.utc)

    for day_offset in range(30):
        day = now - timedelta(days=day_offset)
        day_requests = 30 if day.weekday() < 5 else 10
        day_requests = int(day_requests * random.uniform(0.7, 1.3))

        for _ in range(day_requests):
            provider = random.choice(list(MODEL_DATA.keys()))
            model_name, avg_input, avg_output = random.choice(MODEL_DATA[provider])

            api_key_id = random.choice(api_key_ids)
            provider_key_id = random.choice(provider_key_ids.get(provider, [None]))

            input_tokens = int(avg_input * random.uniform(0.3, 2.0))
            output_tokens = int(avg_output * random.uniform(0.3, 2.0))

            cache_read_tokens = 0
            if random.random() < 0.2:
                cache_read_tokens = int(input_tokens * random.uniform(0.3, 0.8))
                input_tokens -= cache_read_tokens

            reasoning_tokens = 0
            if "o1" in model_name and random.random() < 0.9:
                reasoning_tokens = int(output_tokens * random.uniform(1.0, 5.0))

            hour = random.randint(8, 22)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            timestamp = day.replace(hour=hour, minute=minute, second=second)

            log = UsageLog(
                api_key_id=api_key_id,
                provider_key_id=provider_key_id,
                provider=provider,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                reasoning_tokens=reasoning_tokens,
                latency_ms=int(random.uniform(200, 3000)),
                created_at=timestamp,
                app_id=random.choice(APP_IDS),
                end_user_id=random.choice(USER_IDS),
                cost_cents=0,
            )
            db.add(log)
            summary["usage_logs"] += 1

    await db.commit()
    return summary
