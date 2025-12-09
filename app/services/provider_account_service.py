"""
Provider account service - manages provider accounts.

A ProviderAccount represents an account with a provider (e.g., an OpenAI organization).
Accounts belong to groups and can have multiple API keys.
"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import ProviderAccount, ProviderKey


class ProviderAccountService:
    """Service for managing provider accounts."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(
        self,
        account_id: str,
        include_keys: bool = False,
    ) -> Optional[ProviderAccount]:
        """Get a provider account by ID."""
        query = select(ProviderAccount).where(ProviderAccount.id == account_id)
        if include_keys:
            query = query.options(selectinload(ProviderAccount.keys))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_all_for_group(
        self,
        group_id: str,
        provider_id: Optional[str] = None,
        include_keys: bool = False,
    ) -> list[ProviderAccount]:
        """Get all provider accounts for a group, optionally filtered by provider."""
        query = select(ProviderAccount).where(ProviderAccount.group_id == group_id)
        if provider_id:
            query = query.where(ProviderAccount.provider_id == provider_id)
        if include_keys:
            query = query.options(selectinload(ProviderAccount.keys))
        query = query.order_by(ProviderAccount.provider_id, ProviderAccount.name)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_provider(
        self,
        group_id: str,
        provider_id: str,
        include_keys: bool = False,
    ) -> list[ProviderAccount]:
        """Get all accounts for a specific provider in a group."""
        return await self.get_all_for_group(
            group_id, provider_id=provider_id, include_keys=include_keys
        )

    async def name_exists(
        self,
        group_id: str,
        provider_id: str,
        name: str,
        exclude_id: Optional[str] = None,
    ) -> bool:
        """Check if an account with this name already exists for this provider in the group."""
        query = select(ProviderAccount).where(
            ProviderAccount.group_id == group_id,
            ProviderAccount.provider_id == provider_id,
            ProviderAccount.name == name,
        )
        if exclude_id:
            query = query.where(ProviderAccount.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        group_id: str,
        provider_id: str,
        name: str,
        created_by_id: str,
        external_account_id: Optional[str] = None,
        account_email: Optional[str] = None,
        billing_email: Optional[str] = None,
        account_phone: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ProviderAccount:
        """Create a new provider account."""
        account = ProviderAccount(
            group_id=group_id,
            provider_id=provider_id.lower(),
            name=name.strip(),
            external_account_id=external_account_id.strip() if external_account_id else None,
            account_email=account_email.strip() if account_email else None,
            billing_email=billing_email.strip() if billing_email else None,
            account_phone=account_phone.strip() if account_phone else None,
            notes=notes.strip() if notes else None,
            created_by_id=created_by_id,
            is_active=True,
        )
        self.db.add(account)
        await self.db.commit()
        await self.db.refresh(account)
        return account

    async def update(
        self,
        account_id: str,
        name: Optional[str] = None,
        external_account_id: Optional[str] = None,
        account_email: Optional[str] = None,
        billing_email: Optional[str] = None,
        account_phone: Optional[str] = None,
        notes: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[ProviderAccount]:
        """Update a provider account's metadata."""
        account = await self.get_by_id(account_id)
        if not account:
            return None

        if name is not None:
            account.name = name.strip()
        if external_account_id is not None:
            account.external_account_id = external_account_id.strip() if external_account_id else None
        if account_email is not None:
            account.account_email = account_email.strip() if account_email else None
        if billing_email is not None:
            account.billing_email = billing_email.strip() if billing_email else None
        if account_phone is not None:
            account.account_phone = account_phone.strip() if account_phone else None
        if notes is not None:
            account.notes = notes.strip() if notes else None
        if is_active is not None:
            account.is_active = is_active

        await self.db.commit()
        return account

    async def delete(self, account_id: str) -> bool:
        """
        Delete a provider account.

        Note: This will cascade delete all associated provider keys.
        """
        account = await self.get_by_id(account_id)
        if not account:
            return False

        await self.db.delete(account)
        await self.db.commit()
        return True

    async def get_or_create_default(
        self,
        group_id: str,
        provider_id: str,
        created_by_id: str,
    ) -> ProviderAccount:
        """
        Get the first account for a provider in a group, or create a default one.

        This is useful when adding a key but no account exists yet.
        """
        accounts = await self.get_by_provider(group_id, provider_id)
        if accounts:
            return accounts[0]

        # Create a default account
        return await self.create(
            group_id=group_id,
            provider_id=provider_id,
            name="Default",
            created_by_id=created_by_id,
        )
