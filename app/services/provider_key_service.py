"""
Provider key service - handles provider key CRUD operations.

ProviderKeys now belong to ProviderAccounts, which belong to Groups.
The hierarchy is: Group → ProviderAccount → ProviderKey
"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import ProviderKey, ProviderAccount
from app.auth import encrypt_api_key, decrypt_api_key


class ProviderKeyService:
    """Service for managing provider API keys (OpenAI, Anthropic, etc.)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(
        self,
        key_id: str,
        user_id: Optional[str] = None,
        include_account: bool = False,
    ) -> Optional[ProviderKey]:
        """Get a provider key by ID, optionally verifying creator ownership."""
        query = select(ProviderKey).where(ProviderKey.id == key_id)
        if user_id:
            query = query.where(ProviderKey.user_id == user_id)
        if include_account:
            query = query.options(selectinload(ProviderKey.account))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_all_for_account(
        self,
        account_id: str,
        active_only: bool = True,
    ) -> list[ProviderKey]:
        """Get all provider keys for a specific account."""
        query = select(ProviderKey).where(ProviderKey.provider_account_id == account_id)
        if active_only:
            query = query.where(ProviderKey.is_active == True)
        query = query.order_by(ProviderKey.name)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_all_for_group(
        self,
        group_id: str,
        provider_id: Optional[str] = None,
        include_account: bool = False,
    ) -> list[ProviderKey]:
        """Get all provider keys for a group (via accounts)."""
        query = (
            select(ProviderKey)
            .join(ProviderAccount)
            .where(ProviderAccount.group_id == group_id)
        )
        if provider_id:
            query = query.where(ProviderAccount.provider_id == provider_id)
        if include_account:
            query = query.options(selectinload(ProviderKey.account))
        query = query.order_by(ProviderAccount.provider_id, ProviderAccount.name, ProviderKey.name)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_default_for_provider(
        self,
        group_id: str,
        provider_id: str,
    ) -> Optional[ProviderKey]:
        """Get the default key for a provider in a group.

        Falls back to first key if no default is explicitly set.
        """
        # First try to get the one marked as default
        result = await self.db.execute(
            select(ProviderKey)
            .join(ProviderAccount)
            .where(
                ProviderAccount.group_id == group_id,
                ProviderAccount.provider_id == provider_id,
                ProviderKey.is_default == True,
                ProviderKey.is_active == True,
            )
        )
        key = result.scalar_one_or_none()
        if key:
            return key

        # Otherwise get the first active one
        result = await self.db.execute(
            select(ProviderKey)
            .join(ProviderAccount)
            .where(
                ProviderAccount.group_id == group_id,
                ProviderAccount.provider_id == provider_id,
                ProviderKey.is_active == True,
            )
            .order_by(ProviderKey.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def name_exists(
        self,
        account_id: str,
        name: str,
        exclude_id: Optional[str] = None,
    ) -> bool:
        """Check if a key with this name already exists in the account."""
        query = select(ProviderKey).where(
            ProviderKey.provider_account_id == account_id,
            ProviderKey.name == name,
        )
        if exclude_id:
            query = query.where(ProviderKey.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        provider_account_id: str,
        user_id: str,
        key: str,
        name: str,
        is_default: bool = False,
    ) -> ProviderKey:
        """
        Create a new provider key.

        Args:
            provider_account_id: The account this key belongs to
            user_id: The ID of the user creating the key (audit trail)
            key: The actual API key to store (will be encrypted)
            name: Display name for the key
            is_default: Whether this should be the default for its provider
        """
        # Get the account to find its group and provider
        account_result = await self.db.execute(
            select(ProviderAccount).where(ProviderAccount.id == provider_account_id)
        )
        account = account_result.scalar_one_or_none()
        if not account:
            raise ValueError(f"Provider account not found: {provider_account_id}")

        # If this is marked as default, unset any existing defaults
        if is_default:
            await self._clear_default_for_provider(account.group_id, account.provider_id)

        # If this is the first key for this provider (in this group), make it default
        existing = await self.get_all_for_group(account.group_id, account.provider_id)
        if not existing:
            is_default = True

        # Extract key suffix (last 4 chars for identification)
        key_suffix = key[-4:] if len(key) >= 4 else key

        provider_key = ProviderKey(
            provider_account_id=provider_account_id,
            user_id=user_id,
            encrypted_key=encrypt_api_key(key),
            name=name.strip(),
            key_suffix=key_suffix,
            is_default=is_default,
            is_active=True,
        )
        self.db.add(provider_key)
        await self.db.commit()
        await self.db.refresh(provider_key)
        return provider_key

    async def update(
        self,
        key_id: str,
        user_id: str,
        name: Optional[str] = None,
        new_key: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[ProviderKey]:
        """
        Update a provider key's metadata or the key itself.
        """
        provider_key = await self.get_by_id(key_id, user_id)
        if not provider_key:
            return None

        if name is not None:
            provider_key.name = name.strip()
        if new_key is not None:
            provider_key.encrypted_key = encrypt_api_key(new_key)
            provider_key.key_suffix = new_key[-4:] if len(new_key) >= 4 else new_key
        if is_active is not None:
            provider_key.is_active = is_active

        await self.db.commit()
        return provider_key

    async def set_default(
        self,
        key_id: str,
        user_id: str,
    ) -> bool:
        """
        Set a provider key as the default for its provider within its group.
        """
        provider_key = await self.get_by_id(key_id, user_id, include_account=True)
        if not provider_key or not provider_key.account:
            return False

        # Clear existing default for this provider (in the same group)
        await self._clear_default_for_provider(
            provider_key.account.group_id,
            provider_key.account.provider_id,
        )

        # Set this one as default
        provider_key.is_default = True
        await self.db.commit()
        return True

    async def delete(self, key_id: str, user_id: str) -> bool:
        """
        Delete a provider key.
        """
        provider_key = await self.get_by_id(key_id, user_id, include_account=True)
        if not provider_key:
            return False

        was_default = provider_key.is_default
        account = provider_key.account

        await self.db.delete(provider_key)
        await self.db.commit()

        # If deleted key was default, set a new default (in same group/provider)
        if was_default and account:
            remaining = await self.get_all_for_group(
                account.group_id, account.provider_id
            )
            if remaining:
                remaining[0].is_default = True
                await self.db.commit()

        return True

    async def decrypt_key(self, key_id: str, user_id: str) -> Optional[str]:
        """
        Decrypt and return the actual API key.
        """
        provider_key = await self.get_by_id(key_id, user_id)
        if not provider_key:
            return None
        return decrypt_api_key(provider_key.encrypted_key)

    async def _clear_default_for_provider(
        self,
        group_id: str,
        provider_id: str,
    ) -> None:
        """Clear the default flag for all keys of a provider in a group."""
        result = await self.db.execute(
            select(ProviderKey)
            .join(ProviderAccount)
            .where(
                ProviderAccount.group_id == group_id,
                ProviderAccount.provider_id == provider_id,
                ProviderKey.is_default == True,
            )
        )
        for key in result.scalars().all():
            key.is_default = False

    # Legacy compatibility methods (for gradual migration)

    async def get_all_for_user(
        self,
        user_id: str,
        group_id: Optional[str] = None,
    ) -> list[ProviderKey]:
        """
        Get all provider keys created by a user.

        DEPRECATED: Use get_all_for_group() instead.
        This is kept for backward compatibility during migration.
        """
        if group_id:
            return await self.get_all_for_group(group_id)

        # Fallback: get all keys created by user
        query = select(ProviderKey).where(ProviderKey.user_id == user_id)
        query = query.options(selectinload(ProviderKey.account))
        result = await self.db.execute(query)
        return list(result.scalars().all())
