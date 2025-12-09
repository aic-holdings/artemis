#!/usr/bin/env python3
"""
Seed data script for Artemis.

Creates test users, API keys, provider keys, pricing history, and usage logs
by calling the actual API endpoints (with mocked provider responses).

Usage:
    python scripts/seed_data.py [--base-url http://localhost:8767]
"""

import argparse
import random
import sys
import os
import httpx
from datetime import datetime, timedelta, date
from typing import Optional

# Add parent directory to path to import app.config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings

# Configuration - use settings from app config
DEFAULT_BASE_URL = f"http://localhost:{settings.DEFAULT_PORT}"

# Test data - Demo user for fake data
DEMO_USER = {
    "email": "demo@artemis.dev",
    "password": "demopassword123"
}

# Demo organization name
DEMO_ORG_NAME = "Demo Organization"

API_KEY_NAMES = ["Production", "Development", "Staging", "CI/CD"]

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

# Models and their typical token counts (avg_input, avg_output)
# Cost is calculated dynamically from ModelPricing table
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
# Format: {provider: {model: {effective_date: pricing_dict}}}
PRICING_HISTORY = {
    "openai": {
        "gpt-4o": {
            "2024-01-01": {"input": 500, "output": 1500, "cache_read_mult": 0.5},
            "2024-06-01": {"input": 250, "output": 1000, "cache_read_mult": 0.5},  # Price drop
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
        "o1-preview": {
            "2024-09-01": {"input": 1500, "output": 6000, "reasoning": 6000, "cache_read_mult": 0.5},
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
        "claude-3-5-haiku-20241022": {
            "2024-10-22": {"input": 100, "output": 500, "cache_read_mult": 0.1, "cache_write_mult": 1.25},
        },
    },
    "google": {
        "gemini-1.5-pro": {
            "2024-01-01": {"input": 350, "output": 1050, "cache_read_mult": 0.25},
            "2024-05-01": {"input": 125, "output": 500, "cache_read_mult": 0.25, "long_ctx_threshold": 200000, "long_ctx_mult": 2.0},
        },
        "gemini-1.5-flash": {
            "2024-05-01": {"input": 7.5, "output": 30, "cache_read_mult": 0.25},
        },
        "gemini-2.0-flash-exp": {
            "2024-12-01": {"input": 0, "output": 0},  # Free preview
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
            "2024-01-01": {"input": 320, "output": 1600},  # Slight markup over direct
        },
        "openai/gpt-4o": {
            "2024-01-01": {"input": 270, "output": 1100},
        },
        "meta-llama/llama-3.1-70b-instruct": {
            "2024-01-01": {"input": 52, "output": 75},
        },
    },
}


class SeedDataClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(follow_redirects=True, timeout=30.0)
        self.session_cookie: Optional[str] = None
        self.api_key: Optional[str] = None
        self.api_key_ids: list[str] = []
        self.provider_key_ids: dict[str, list[str]] = {}

    def register_and_login(self):
        """Register demo user and login."""
        print(f"Registering user {DEMO_USER['email']}...")

        # Try to register (may fail if user exists)
        response = self.client.post(
            f"{self.base_url}/register",
            data=DEMO_USER,
        )

        # Login
        print("Logging in...")
        response = self.client.post(
            f"{self.base_url}/login",
            data=DEMO_USER,
        )

        # Store session cookie
        cookies = response.cookies
        if "session" in cookies:
            self.session_cookie = cookies["session"]
            self.client.cookies.set("session", self.session_cookie)

        print("Logged in successfully!")

    def create_api_keys(self):
        """Create API keys directly in database for demo user, assigned to the demo group."""
        print("\nCreating API keys...")

        import sys
        sys.path.insert(0, ".")

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import APIKey, User, Group, Organization
        from app.auth import generate_api_key, encrypt_api_key
        from app.config import settings

        # Use DATABASE_URL from settings, converting async to sync
        db_url = settings.DATABASE_URL
        if "+asyncpg" in db_url:
            db_url = db_url.replace("+asyncpg", "+psycopg2")
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Get the demo user
        demo_user = session.query(User).filter_by(email=DEMO_USER["email"]).first()
        if not demo_user:
            print("  Error: Demo user not found!")
            session.close()
            return

        # Get the demo organization's default group
        demo_org = session.query(Organization).filter_by(name=DEMO_ORG_NAME).first()
        demo_group = None
        if demo_org:
            demo_group = session.query(Group).filter_by(
                organization_id=demo_org.id,
                is_default=True
            ).first()

        if not demo_group:
            print("  Warning: Demo group not found - keys will be created without group assignment")
            print("  Run seed_organization() first to create groups")

        for name in API_KEY_NAMES:
            # Check if key already exists in this group
            existing = session.query(APIKey).filter_by(
                group_id=demo_group.id if demo_group else None,
                name=name
            ).first()
            if existing:
                if not self.api_key and existing.encrypted_key:
                    from app.auth import decrypt_api_key
                    self.api_key = decrypt_api_key(existing.encrypted_key)
                self.api_key_ids.append(existing.id)
                continue

            full_key, key_hash, key_prefix = generate_api_key()

            api_key = APIKey(
                group_id=demo_group.id if demo_group else None,
                user_id=demo_user.id,  # Created by demo user (audit trail)
                key_hash=key_hash,
                key_prefix=key_prefix,
                encrypted_key=encrypt_api_key(full_key),
                name=name,
            )
            session.add(api_key)
            session.commit()

            self.api_key_ids.append(api_key.id)
            if not self.api_key:
                self.api_key = full_key
                print(f"  Created key '{name}': {full_key[:20]}...")
            else:
                print(f"  Created key '{name}'")

        session.close()
        print(f"  Total API keys created: {len(self.api_key_ids)}")

    def seed_providers(self):
        """Seed the Provider reference table with default providers."""
        print("\nSeeding providers...")

        import sys
        sys.path.insert(0, ".")

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import Provider

        # Use DATABASE_URL from settings, converting async to sync
        db_url = settings.DATABASE_URL
        if "+asyncpg" in db_url:
            db_url = db_url.replace("+asyncpg", "+psycopg2")
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Default provider configurations
        default_providers = [
            {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "docs_url": "https://platform.openai.com/docs"},
            {"id": "anthropic", "name": "Anthropic", "base_url": "https://api.anthropic.com", "docs_url": "https://docs.anthropic.com"},
            {"id": "google", "name": "Google", "base_url": "https://generativelanguage.googleapis.com", "docs_url": "https://ai.google.dev/docs"},
            {"id": "perplexity", "name": "Perplexity", "base_url": "https://api.perplexity.ai", "docs_url": "https://docs.perplexity.ai"},
            {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "docs_url": "https://openrouter.ai/docs"},
        ]

        created = 0
        for config in default_providers:
            existing = session.query(Provider).filter_by(id=config["id"]).first()
            if not existing:
                provider = Provider(
                    id=config["id"],
                    name=config["name"],
                    base_url=config.get("base_url"),
                    docs_url=config.get("docs_url"),
                    is_active=True,
                )
                session.add(provider)
                created += 1

        session.commit()
        session.close()
        print(f"  Created {created} providers")

    def create_provider_keys(self):
        """Create provider accounts and keys directly in database for demo user."""
        print("\nCreating provider accounts and keys...")

        import sys
        sys.path.insert(0, ".")

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import ProviderKey, ProviderAccount, User, Group, Organization
        from app.auth import encrypt_api_key

        # Use DATABASE_URL from settings, converting async to sync
        db_url = settings.DATABASE_URL
        if "+asyncpg" in db_url:
            db_url = db_url.replace("+asyncpg", "+psycopg2")
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Get the demo user
        demo_user = session.query(User).filter_by(email=DEMO_USER["email"]).first()
        if not demo_user:
            print("  Error: Demo user not found!")
            session.close()
            return

        # Get the demo organization's default group
        demo_org = session.query(Organization).filter_by(name=DEMO_ORG_NAME).first()
        demo_group = None
        if demo_org:
            demo_group = session.query(Group).filter_by(
                organization_id=demo_org.id,
                is_default=True
            ).first()

        if not demo_group:
            print("  Warning: Demo group not found - provider keys will be created without group assignment")
            print("  Run seed_organization() first to create groups")
            session.close()
            return

        total_accounts = 0
        total_keys = 0

        for provider_id, accounts in PROVIDER_ACCOUNTS.items():
            self.provider_key_ids[provider_id] = []
            is_first_key_for_provider = True

            for account_data in accounts:
                # Check if account already exists
                existing_account = session.query(ProviderAccount).filter_by(
                    group_id=demo_group.id,
                    provider_id=provider_id,
                    name=account_data["name"]
                ).first()

                if existing_account:
                    account = existing_account
                else:
                    # Create the provider account
                    account = ProviderAccount(
                        group_id=demo_group.id,
                        provider_id=provider_id,
                        name=account_data["name"],
                        account_email=account_data.get("email"),
                        account_phone=account_data.get("phone"),
                        created_by_id=demo_user.id,
                        is_active=True,
                    )
                    session.add(account)
                    session.commit()
                    total_accounts += 1
                    print(f"  Created {provider_id} account: {account_data['name']}")

                # Check if key already exists for this account
                existing_key = session.query(ProviderKey).filter_by(
                    provider_account_id=account.id,
                    name="Default Key"
                ).first()

                if existing_key:
                    self.provider_key_ids[provider_id].append(existing_key.id)
                    is_first_key_for_provider = False
                    continue

                # Create a key for each account
                fake_key = f"sk-fake-{provider_id}-{account_data['name'].lower().replace(' ', '-')}-12345"

                provider_key = ProviderKey(
                    provider_account_id=account.id,
                    user_id=demo_user.id,  # Created by demo user (audit trail)
                    encrypted_key=encrypt_api_key(fake_key),
                    name="Default Key",
                    key_suffix=fake_key[-4:],
                    is_default=is_first_key_for_provider,  # First key per provider is default within this group
                    is_active=True,
                )
                session.add(provider_key)
                session.commit()

                self.provider_key_ids[provider_id].append(provider_key.id)
                total_keys += 1
                is_first_key_for_provider = False

        session.close()
        print(f"  Total accounts created: {total_accounts}")
        print(f"  Total keys created: {total_keys}")

    def seed_organization(self):
        """Create Demo Organization and AIC Holdings with default groups.

        Creates:
        1. Demo Organization with "Default" group
        2. AIC Holdings with "Default" group
        3. Adds dshanklin as owner of both orgs and their default groups
        4. Adds demo user to Demo Org's default group as member

        Groups have roles: owner (can manage members), admin (can edit), member (can view/use)
        """
        print("\nSeeding organizations and groups...")

        import sys
        sys.path.insert(0, ".")

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import Organization, User, Group, GroupMember

        # Use DATABASE_URL from settings, converting async to sync
        db_url = settings.DATABASE_URL
        if "+asyncpg" in db_url:
            db_url = db_url.replace("+asyncpg", "+psycopg2")
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Get the localhost user (dshanklin@aicholdings.com)
        localhost_user = session.query(User).filter_by(email="dshanklin@aicholdings.com").first()
        if not localhost_user:
            print("  Warning: Localhost user dshanklin@aicholdings.com not found!")

        # Get demo user
        demo_user = session.query(User).filter_by(email=DEMO_USER["email"]).first()

        # Store group IDs for later use
        self.demo_group_id = None
        self.aic_group_id = None

        # Create or get Demo Organization, set owner
        demo_org = session.query(Organization).filter_by(name=DEMO_ORG_NAME).first()
        if not demo_org:
            demo_org = Organization(name=DEMO_ORG_NAME, owner_id=localhost_user.id if localhost_user else None)
            session.add(demo_org)
            session.commit()
            print(f"  Created organization: {DEMO_ORG_NAME}")
        else:
            # Update owner if not set
            if not demo_org.owner_id and localhost_user:
                demo_org.owner_id = localhost_user.id
                session.commit()
                print(f"  Set owner of {DEMO_ORG_NAME} to dshanklin@aicholdings.com")
            else:
                print(f"  Organization already exists: {DEMO_ORG_NAME}")

        # Create default group for Demo Organization
        demo_default_group = session.query(Group).filter_by(
            organization_id=demo_org.id,
            is_default=True
        ).first()
        if not demo_default_group:
            demo_default_group = Group(
                organization_id=demo_org.id,
                name="Default",
                description="Default group for all organization members",
                is_default=True,
                created_by_id=localhost_user.id if localhost_user else None
            )
            session.add(demo_default_group)
            session.commit()
            print(f"  Created default group for {DEMO_ORG_NAME}")
        else:
            print(f"  Default group already exists for {DEMO_ORG_NAME}")

        self.demo_group_id = demo_default_group.id

        # Add dshanklin as owner of Demo default group
        if localhost_user:
            demo_owner_membership = session.query(GroupMember).filter_by(
                group_id=demo_default_group.id,
                user_id=localhost_user.id
            ).first()
            if not demo_owner_membership:
                demo_owner_membership = GroupMember(
                    group_id=demo_default_group.id,
                    user_id=localhost_user.id,
                    role="owner"
                )
                session.add(demo_owner_membership)
                session.commit()
                print(f"  Added dshanklin as owner of {DEMO_ORG_NAME}'s Default group")

        # Add demo user as member of Demo default group
        if demo_user:
            demo_member = session.query(GroupMember).filter_by(
                group_id=demo_default_group.id,
                user_id=demo_user.id
            ).first()
            if not demo_member:
                demo_member = GroupMember(
                    group_id=demo_default_group.id,
                    user_id=demo_user.id,
                    role="member",
                    added_by_id=localhost_user.id if localhost_user else None
                )
                session.add(demo_member)
                session.commit()
                print(f"  Added demo user as member of {DEMO_ORG_NAME}'s Default group")

        # Create or get AIC Holdings organization, set owner
        aic_org = session.query(Organization).filter_by(name="AIC Holdings").first()
        if not aic_org:
            aic_org = Organization(name="AIC Holdings", owner_id=localhost_user.id if localhost_user else None)
            session.add(aic_org)
            session.commit()
            print(f"  Created organization: AIC Holdings")
        else:
            # Update owner if not set
            if not aic_org.owner_id and localhost_user:
                aic_org.owner_id = localhost_user.id
                session.commit()
                print(f"  Set owner of AIC Holdings to dshanklin@aicholdings.com")
            else:
                print(f"  Organization already exists: AIC Holdings")

        # Create default group for AIC Holdings
        aic_default_group = session.query(Group).filter_by(
            organization_id=aic_org.id,
            is_default=True
        ).first()
        if not aic_default_group:
            aic_default_group = Group(
                organization_id=aic_org.id,
                name="Default",
                description="Default group for all organization members",
                is_default=True,
                created_by_id=localhost_user.id if localhost_user else None
            )
            session.add(aic_default_group)
            session.commit()
            print(f"  Created default group for AIC Holdings")
        else:
            print(f"  Default group already exists for AIC Holdings")

        self.aic_group_id = aic_default_group.id

        # Add dshanklin as owner of AIC Holdings default group
        if localhost_user:
            aic_owner_membership = session.query(GroupMember).filter_by(
                group_id=aic_default_group.id,
                user_id=localhost_user.id
            ).first()
            if not aic_owner_membership:
                aic_owner_membership = GroupMember(
                    group_id=aic_default_group.id,
                    user_id=localhost_user.id,
                    role="owner"
                )
                session.add(aic_owner_membership)
                session.commit()
                print(f"  Added dshanklin as owner of AIC Holdings's Default group")

        # Link demo user to Demo Organization (legacy field)
        if demo_user and not demo_user.organization_id:
            demo_user.organization_id = demo_org.id
            session.commit()
            print(f"  Linked user {DEMO_USER['email']} to {DEMO_ORG_NAME}")

        # Summary
        if localhost_user:
            print(f"  User dshanklin@aicholdings.com owns: {DEMO_ORG_NAME}, AIC Holdings")
            print(f"    -> Keys/data belong to groups within these orgs")
            print(f"    -> Switch orgs via Settings or user dropdown")

        session.close()

    def seed_pricing_history(self):
        """Seed the ModelPricing table with historical pricing data."""
        print("\nSeeding pricing history...")

        import sys
        sys.path.insert(0, ".")

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import ModelPricing

        # Use DATABASE_URL from settings, converting async to sync
        db_url = settings.DATABASE_URL
        if "+asyncpg" in db_url:
            db_url = db_url.replace("+asyncpg", "+psycopg2")
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        total_created = 0

        for provider, models in PRICING_HISTORY.items():
            for model, date_pricing in models.items():
                for date_str, pricing in date_pricing.items():
                    effective_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                    # Check if pricing already exists
                    existing = session.query(ModelPricing).filter_by(
                        provider=provider,
                        model=model,
                        effective_date=effective_date
                    ).first()

                    if existing:
                        continue

                    mp = ModelPricing(
                        provider=provider,
                        model=model,
                        effective_date=effective_date,
                        input_price_per_1m=pricing.get("input", 0),
                        output_price_per_1m=pricing.get("output", 0),
                        cache_read_multiplier=pricing.get("cache_read_mult"),
                        cache_write_multiplier=pricing.get("cache_write_mult"),
                        reasoning_price_per_1m=pricing.get("reasoning"),
                        image_input_price_per_1m=pricing.get("image_input"),
                        audio_input_price_per_1m=pricing.get("audio_input"),
                        audio_output_price_per_1m=pricing.get("audio_output"),
                        video_input_price_per_1m=pricing.get("video_input"),
                        batch_discount=pricing.get("batch_discount", 0.5),
                        long_context_threshold=pricing.get("long_ctx_threshold"),
                        long_context_multiplier=pricing.get("long_ctx_mult"),
                        notes=f"Seeded from seed_data.py"
                    )
                    session.add(mp)
                    total_created += 1

        session.commit()
        session.close()
        print(f"  Created {total_created} pricing entries!")

    def create_usage_logs(self, num_days: int = 90, requests_per_day: int = 50):
        """Create usage logs with varied token types.

        This directly inserts usage logs into the database since we can't
        actually make LLM requests with fake keys.
        """
        print(f"\nCreating usage logs ({num_days} days, ~{requests_per_day} requests/day)...")

        import sys
        sys.path.insert(0, ".")

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import UsageLog, APIKey, ProviderKey, ProviderAccount

        # Use DATABASE_URL from settings, converting async to sync
        db_url = settings.DATABASE_URL
        if "+asyncpg" in db_url:
            db_url = db_url.replace("+asyncpg", "+psycopg2")
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Get actual IDs from database
        api_keys = session.query(APIKey).filter(APIKey.revoked_at.is_(None)).all()

        # Get provider keys with their account info to build provider lookup
        provider_keys = session.query(ProviderKey, ProviderAccount.provider_id).join(
            ProviderAccount, ProviderKey.provider_account_id == ProviderAccount.id
        ).all()

        if not api_keys:
            print("  Error: No API keys found!")
            return

        # Build provider key lookup: {provider_id: [ProviderKey, ...]}
        pk_by_provider = {}
        for pk, provider_id in provider_keys:
            if provider_id not in pk_by_provider:
                pk_by_provider[provider_id] = []
            pk_by_provider[provider_id].append(pk)

        total_created = 0
        now = datetime.now()

        for day_offset in range(num_days):
            day = now - timedelta(days=day_offset)

            # Vary requests per day (weekends have less)
            day_requests = requests_per_day
            if day.weekday() >= 5:  # Weekend
                day_requests = int(requests_per_day * 0.3)

            # Add some randomness
            day_requests = int(day_requests * random.uniform(0.7, 1.3))

            for _ in range(day_requests):
                # Pick random provider and model
                provider = random.choice(list(MODEL_DATA.keys()))
                model_name, avg_input, avg_output = random.choice(MODEL_DATA[provider])

                # Random API key
                api_key = random.choice(api_keys)

                # Provider key for this provider (if available)
                provider_key = None
                if provider in pk_by_provider and pk_by_provider[provider]:
                    provider_key = random.choice(pk_by_provider[provider])

                # Random tokens with variation
                input_tokens = int(avg_input * random.uniform(0.3, 2.0))
                output_tokens = int(avg_output * random.uniform(0.3, 2.0))

                # Sometimes add cache tokens (20% chance)
                cache_read_tokens = 0
                cache_write_tokens = 0
                if random.random() < 0.2:
                    # Cached requests have some tokens from cache
                    cache_read_tokens = int(input_tokens * random.uniform(0.3, 0.8))
                    input_tokens -= cache_read_tokens  # Cache reads replace some input
                if random.random() < 0.05:
                    # Cache write (less common)
                    cache_write_tokens = int(input_tokens * random.uniform(0.1, 0.3))

                # Sometimes add reasoning tokens for o1 models (10% of o1 requests)
                reasoning_tokens = 0
                if "o1" in model_name and random.random() < 0.9:
                    reasoning_tokens = int(output_tokens * random.uniform(1.0, 5.0))

                # Rarely add image tokens (5% chance for relevant models)
                image_input_tokens = 0
                if provider in ["openai", "anthropic", "google"] and random.random() < 0.05:
                    image_input_tokens = random.randint(500, 3000)

                # Total context for long context pricing
                total_context = input_tokens + cache_read_tokens + cache_write_tokens

                # Random latency
                latency_ms = int(random.uniform(200, 3000))

                # Random timestamp within the day
                hour = random.randint(8, 22)  # Business-ish hours
                minute = random.randint(0, 59)
                second = random.randint(0, 59)
                timestamp = day.replace(hour=hour, minute=minute, second=second)

                # Random batch flag (10% are batch)
                is_batch = random.random() < 0.1

                # Create log entry (cost_cents left at 0 - calculated dynamically)
                log = UsageLog(
                    api_key_id=api_key.id,
                    provider_key_id=provider_key.id if provider_key else None,
                    provider=provider,
                    model=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                    reasoning_tokens=reasoning_tokens,
                    image_input_tokens=image_input_tokens,
                    audio_input_tokens=0,
                    audio_output_tokens=0,
                    video_input_tokens=0,
                    is_batch=is_batch,
                    total_context_tokens=total_context,
                    latency_ms=latency_ms,
                    created_at=timestamp,
                    app_id=random.choice(APP_IDS),
                    end_user_id=random.choice(USER_IDS),
                    cost_cents=0,  # Will be calculated dynamically
                )
                session.add(log)
                total_created += 1

            # Commit every few days to avoid memory issues
            if day_offset % 10 == 0:
                session.commit()
                print(f"  Progress: {day_offset + 1}/{num_days} days...")

        session.commit()
        session.close()
        print(f"  Created {total_created} usage log entries!")

    def print_summary(self):
        """Print summary of created data."""
        print("\n" + "=" * 50)
        print("SEED DATA SUMMARY")
        print("=" * 50)
        print(f"Demo User: {DEMO_USER['email']} / {DEMO_USER['password']}")
        print(f"Demo Org: {DEMO_ORG_NAME}")
        if self.api_key:
            print(f"API Key: {self.api_key}")
        print(f"API Keys Created: {len(self.api_key_ids)}")
        print(f"Provider Keys Created: {len(getattr(self, 'all_provider_key_ids', []))}")
        print("\nTo view the demo data as localhost user:")
        print(f"  1. Visit {self.base_url}/settings")
        print(f"  2. Click '{DEMO_ORG_NAME}' to switch to that org view")
        print(f"  3. Visit {self.base_url}/dashboard to see the demo data")
        print("\nYour personal data remains clean and separate.")
        print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Seed Artemis with test data")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of Artemis server (default: {DEFAULT_BASE_URL})"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days of usage data to create (default: 90)"
    )
    parser.add_argument(
        "--requests-per-day",
        type=int,
        default=50,
        help="Average requests per day (default: 50)"
    )
    args = parser.parse_args()

    client = SeedDataClient(args.base_url)

    try:
        client.register_and_login()
        # Create organization and groups FIRST so keys can be assigned to groups
        client.seed_organization()
        # Seed providers reference table before creating accounts/keys
        client.seed_providers()
        client.create_api_keys()
        client.create_provider_keys()
        client.seed_pricing_history()
        client.create_usage_logs(num_days=args.days, requests_per_day=args.requests_per_day)
        client.print_summary()
    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    main()
