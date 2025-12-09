"""
API key service - handles API key CRUD operations.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import APIKey, ProviderKey
from app.auth import generate_api_key, encrypt_api_key, decrypt_api_key


class APIKeyService:
    """Service for managing Artemis API keys."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, key_id: str, user_id: Optional[str] = None, group_id: Optional[str] = None) -> Optional[APIKey]:
        """
        Get an API key by ID, optionally verifying ownership.

        Args:
            key_id: The API key ID
            user_id: Optional user ID for ownership verification (legacy)
            group_id: Optional group ID for group-based access control
        """
        query = select(APIKey).where(APIKey.id == key_id)
        if user_id:
            query = query.where(APIKey.user_id == user_id)
        if group_id:
            query = query.where(APIKey.group_id == group_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_all_for_user(
        self, user_id: str, include_revoked: bool = True, group_id: Optional[str] = None
    ) -> list[APIKey]:
        """Get all API keys for a user, optionally filtered by group."""
        query = select(APIKey).where(APIKey.user_id == user_id)
        if group_id:
            query = query.where(APIKey.group_id == group_id)
        if not include_revoked:
            query = query.where(APIKey.revoked_at.is_(None))
        query = query.order_by(APIKey.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_all_for_group(self, group_id: str, include_revoked: bool = True) -> list[APIKey]:
        """Get all API keys for a group."""
        query = select(APIKey).where(APIKey.group_id == group_id)
        if not include_revoked:
            query = query.where(APIKey.revoked_at.is_(None))
        query = query.order_by(APIKey.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_active_for_user(self, user_id: str) -> list[APIKey]:
        """Get only active (non-revoked) API keys for a user."""
        return await self.get_all_for_user(user_id, include_revoked=False)

    async def name_exists(
        self, user_id: str, name: str, group_id: Optional[str] = None
    ) -> bool:
        """Check if an active API key with this name already exists.

        If group_id is provided, checks within that group's scope.
        Otherwise checks for user's personal keys (no group).
        """
        query = select(APIKey).where(
            APIKey.user_id == user_id,
            APIKey.name == name,
            APIKey.revoked_at.is_(None)
        )
        if group_id:
            query = query.where(APIKey.group_id == group_id)
        else:
            query = query.where(APIKey.group_id.is_(None))
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def create(
        self, user_id: str, name: str = "Default", group_id: Optional[str] = None
    ) -> tuple[APIKey, str]:
        """
        Create a new API key.

        Args:
            user_id: The ID of the user creating the key
            name: Display name for the key
            group_id: Optional group ID (if key belongs to a group)

        Returns:
            Tuple of (APIKey object, full key string)
            The full key is only available at creation time.
        """
        name = name.strip() or "Default"
        full_key, key_hash, key_prefix = generate_api_key()

        api_key = APIKey(
            user_id=user_id,
            group_id=group_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            encrypted_key=encrypt_api_key(full_key),
            name=name,
        )
        self.db.add(api_key)
        await self.db.commit()
        await self.db.refresh(api_key)

        return api_key, full_key

    async def revoke(self, key_id: str, user_id: str) -> bool:
        """
        Revoke an API key.

        Returns:
            True if key was found and revoked, False otherwise.
        """
        api_key = await self.get_by_id(key_id, user_id)
        if not api_key:
            return False

        api_key.revoked_at = datetime.now(timezone.utc)
        await self.db.commit()
        return True

    async def reveal(self, key_id: str, user_id: str) -> Optional[str]:
        """
        Reveal (decrypt) an API key.

        Returns:
            The full API key string, or None if not found/not decryptable.
        """
        api_key = await self.get_by_id(key_id, user_id)
        if not api_key or not api_key.encrypted_key:
            return None

        return decrypt_api_key(api_key.encrypted_key)

    async def update_provider_overrides(
        self,
        key_id: str,
        user_id: str,
        overrides: dict[str, str]
    ) -> bool:
        """
        Update provider key overrides for an API key.

        Args:
            key_id: The API key ID
            user_id: The user ID (for ownership verification)
            overrides: Dict mapping provider names to provider key IDs

        Returns:
            True if updated successfully, False if key not found.
        """
        api_key = await self.get_by_id(key_id, user_id)
        if not api_key:
            return False

        # Validate that all referenced provider keys belong to this user
        validated_overrides = {}
        for provider, pk_id in overrides.items():
            pk_check = await self.db.execute(
                select(ProviderKey).where(
                    ProviderKey.id == pk_id,
                    ProviderKey.user_id == user_id
                )
            )
            if pk_check.scalar_one_or_none():
                validated_overrides[provider] = pk_id

        api_key.provider_key_overrides = validated_overrides if validated_overrides else None
        await self.db.commit()
        return True

    async def get_default(self, user_id: str, group_id: Optional[str] = None) -> Optional[APIKey]:
        """
        Get the default API key for a user/group.

        Args:
            user_id: The user ID
            group_id: Optional group ID

        Returns:
            The default API key, or None if no default is set.
        """
        query = select(APIKey).where(
            APIKey.user_id == user_id,
            APIKey.is_default == True,
            APIKey.revoked_at.is_(None)
        )
        if group_id:
            query = query.where(APIKey.group_id == group_id)
        else:
            query = query.where(APIKey.group_id.is_(None))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def set_default(self, key_id: str, user_id: str) -> bool:
        """
        Set an API key as the default for its user/group scope.

        Args:
            key_id: The API key ID to set as default
            user_id: The user ID (for ownership verification)

        Returns:
            True if updated successfully, False if key not found.
        """
        api_key = await self.get_by_id(key_id, user_id)
        if not api_key:
            return False

        # Clear any existing default in the same scope
        await self._clear_default(user_id, api_key.group_id)

        # Set the new default
        api_key.is_default = True
        await self.db.commit()
        return True

    async def _clear_default(self, user_id: str, group_id: Optional[str] = None):
        """Clear any existing default key in the given scope."""
        query = select(APIKey).where(
            APIKey.user_id == user_id,
            APIKey.is_default == True
        )
        if group_id:
            query = query.where(APIKey.group_id == group_id)
        else:
            query = query.where(APIKey.group_id.is_(None))
        result = await self.db.execute(query)
        for key in result.scalars().all():
            key.is_default = False
        await self.db.commit()

    # System key constants
    ARTEMIS_TEST_KEY_NAME = "Artemis-Test"

    async def get_or_create_artemis_test_key(
        self, user_id: str, group_id: str
    ) -> tuple[APIKey, Optional[str]]:
        """
        Get or create the Artemis-Test system key for a group.

        This is a special system key used exclusively for chat/vision testing.
        It cannot be edited or deleted by users.

        Args:
            user_id: The user ID (for audit trail if creating)
            group_id: The group ID

        Returns:
            Tuple of (APIKey object, full key string or None if key already existed)
        """
        # Check if Artemis-Test key already exists for this group
        query = select(APIKey).where(
            APIKey.group_id == group_id,
            APIKey.name == self.ARTEMIS_TEST_KEY_NAME,
            APIKey.is_system == True,
            APIKey.revoked_at.is_(None)
        )
        result = await self.db.execute(query)
        existing = result.scalar_one_or_none()

        if existing:
            return existing, None

        # Create the system key
        full_key, key_hash, key_prefix = generate_api_key()

        api_key = APIKey(
            user_id=user_id,
            group_id=group_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            encrypted_key=encrypt_api_key(full_key),
            name=self.ARTEMIS_TEST_KEY_NAME,
            is_system=True,
            is_default=True,  # System key is always the default for chat
        )
        self.db.add(api_key)
        await self.db.commit()
        await self.db.refresh(api_key)

        return api_key, full_key

    async def get_artemis_test_key(self, group_id: str) -> Optional[APIKey]:
        """
        Get the Artemis-Test key for a group.

        Args:
            group_id: The group ID

        Returns:
            The Artemis-Test API key, or None if not found.
        """
        query = select(APIKey).where(
            APIKey.group_id == group_id,
            APIKey.name == self.ARTEMIS_TEST_KEY_NAME,
            APIKey.is_system == True,
            APIKey.revoked_at.is_(None)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
