#!/usr/bin/env python3
"""
Add v0 provider key to Artemis.

Usage:
    DATABASE_URL=... V0_API_KEY=... python scripts/add_v0_key.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select


async def add_v0_key():
    from app.models import Provider, ProviderAccount, ProviderKey, Group
    from app.auth import encrypt_api_key

    database_url = os.environ.get("DATABASE_URL")
    v0_api_key = os.environ.get("V0_API_KEY")

    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return False

    if not v0_api_key:
        print("ERROR: V0_API_KEY not set")
        return False

    engine = create_async_engine(database_url)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Check if v0 provider exists, if not create it
        result = await db.execute(select(Provider).where(Provider.id == "v0"))
        provider = result.scalar_one_or_none()

        if not provider:
            print("Creating v0 provider...")
            provider = Provider(
                id="v0",
                name="v0 (Vercel)",
                base_url="https://api.v0.dev/v1",
                docs_url="https://v0.app/docs/api/model",
                is_active=True
            )
            db.add(provider)
            await db.commit()
            print("  Created v0 provider")
        else:
            print("v0 provider already exists")

        # Find a group to add the key to (use first group found)
        result = await db.execute(select(Group).limit(1))
        group = result.scalar_one_or_none()

        if not group:
            print("ERROR: No groups found in database")
            return False

        print(f"Using group: {group.name} ({group.id})")

        # Check if v0 account exists for this group
        result = await db.execute(
            select(ProviderAccount).where(
                ProviderAccount.group_id == group.id,
                ProviderAccount.provider_id == "v0"
            )
        )
        account = result.scalar_one_or_none()

        if not account:
            print("Creating v0 provider account...")
            account = ProviderAccount(
                group_id=group.id,
                provider_id="v0",
                name="Default"
            )
            db.add(account)
            await db.commit()
            await db.refresh(account)
            print(f"  Created account: {account.id}")
        else:
            print(f"v0 account exists: {account.id}")

        # Check if key already exists
        result = await db.execute(
            select(ProviderKey).where(ProviderKey.provider_account_id == account.id)
        )
        existing_key = result.scalar_one_or_none()

        if existing_key:
            print(f"v0 key already exists: {existing_key.name} (****{existing_key.key_suffix})")
            return True

        # Add the key
        print("Adding v0 API key...")
        key_suffix = v0_api_key[-4:] if len(v0_api_key) >= 4 else v0_api_key

        provider_key = ProviderKey(
            provider_account_id=account.id,
            encrypted_key=encrypt_api_key(v0_api_key),
            name="v0 API Key",
            key_suffix=key_suffix,
            is_default=True,
            is_active=True
        )
        db.add(provider_key)
        await db.commit()
        print(f"  Added key: v0 API Key (****{key_suffix})")

    await engine.dispose()
    print("\nDone! v0 provider key configured.")
    return True


if __name__ == "__main__":
    success = asyncio.run(add_v0_key())
    sys.exit(0 if success else 1)
