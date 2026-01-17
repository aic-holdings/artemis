#!/usr/bin/env python3
"""
Fix corrupted provider keys by deleting them.
They'll need to be re-added through the Artemis UI after ENCRYPTION_KEY is updated.

Run locally with: python scripts/fix_provider_keys.py
"""

import asyncio
import os
import sys

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Production database URL (via SSH tunnel or direct if accessible)
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://artemis:artemis_prod_2024@localhost:5433/artemis"
)


async def fix_provider_keys():
    """Delete all corrupted provider keys."""
    print(f"Connecting to: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")

    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Count existing keys
        result = await session.execute(text("SELECT COUNT(*) FROM provider_keys"))
        count = result.scalar()
        print(f"Found {count} provider keys")

        if count == 0:
            print("No keys to delete")
            return

        # List keys before deletion
        result = await session.execute(text("""
            SELECT pk.id, pk.name, pk.key_suffix, pa.provider_id
            FROM provider_keys pk
            JOIN provider_accounts pa ON pk.provider_account_id = pa.id
        """))
        keys = result.fetchall()

        print("\nProvider keys to delete:")
        for key in keys:
            print(f"  - {key[3]}: {key[1]} (...{key[2]})")

        # Confirm
        confirm = input("\nDelete these keys? [y/N]: ")
        if confirm.lower() != 'y':
            print("Aborted")
            return

        # Delete all provider keys
        await session.execute(text("DELETE FROM provider_keys"))
        await session.commit()

        print(f"\nDeleted {count} provider keys")
        print("Now re-add them through Artemis UI at https://artemis.jettaintelligence.com")


if __name__ == "__main__":
    asyncio.run(fix_provider_keys())
