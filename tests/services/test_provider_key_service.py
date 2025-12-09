"""Tests for ProviderKeyService."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.provider_key_service import ProviderKeyService
from app.models import User, ProviderKey
from app.auth import decrypt_api_key


class TestProviderKeyServiceCreate:
    """Test provider key creation via service."""

    @pytest.mark.asyncio
    async def test_create_provider_key(self, test_db):
        """Create a new provider key."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            provider_key = await service.create(
                user_id=user.id,
                provider="openai",
                key="sk-test-key-12345",
                name="My OpenAI Key",
            )

            assert provider_key is not None
            assert provider_key.provider == "openai"
            assert provider_key.name == "My OpenAI Key"
            assert provider_key.user_id == user.id
            assert provider_key.is_default is True  # First key is auto-default

    @pytest.mark.asyncio
    async def test_create_provider_key_with_metadata(self, test_db):
        """Create provider key with account metadata."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            provider_key = await service.create(
                user_id=user.id,
                provider="anthropic",
                key="sk-ant-12345",
                name="Work Account",
                account_email="work@company.com",
                account_phone="+1-555-1234",
            )

            assert provider_key.account_email == "work@company.com"
            assert provider_key.account_phone == "+1-555-1234"

    @pytest.mark.asyncio
    async def test_first_key_auto_default(self, test_db):
        """First key for a provider is automatically default."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            key1 = await service.create(
                user_id=user.id,
                provider="openai",
                key="sk-key1",
                name="Key 1",
                is_default=False,  # Explicitly set false
            )

            # First key should still be default
            assert key1.is_default is True

    @pytest.mark.asyncio
    async def test_second_key_not_auto_default(self, test_db):
        """Second key is not automatically default."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            await service.create(
                user_id=user.id,
                provider="openai",
                key="sk-key1",
                name="Key 1",
            )
            key2 = await service.create(
                user_id=user.id,
                provider="openai",
                key="sk-key2",
                name="Key 2",
            )

            assert key2.is_default is False


class TestProviderKeyServiceGet:
    """Test provider key retrieval."""

    @pytest.mark.asyncio
    async def test_get_by_id(self, test_db):
        """Get provider key by ID."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            created = await service.create(
                user_id=user.id,
                provider="openai",
                key="sk-test",
                name="Test Key",
            )

            found = await service.get_by_id(created.id, user.id)
            assert found is not None
            assert found.id == created.id
            assert found.name == "Test Key"

    @pytest.mark.asyncio
    async def test_get_by_id_wrong_user(self, test_db):
        """Cannot get provider key for different user."""
        async with test_db() as session:
            user1 = User(email="user1@example.com", password_hash="hash123")
            user2 = User(email="user2@example.com", password_hash="hash456")
            session.add(user1)
            session.add(user2)
            await session.commit()
            await session.refresh(user1)
            await session.refresh(user2)

            service = ProviderKeyService(session)
            created = await service.create(
                user_id=user1.id,
                provider="openai",
                key="sk-test",
                name="User1 Key",
            )

            # User2 cannot access User1's key
            found = await service.get_by_id(created.id, user2.id)
            assert found is None

    @pytest.mark.asyncio
    async def test_get_all_for_user(self, test_db):
        """Get all provider keys for a user."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            await service.create(user.id, "openai", "sk-1", "OpenAI Key")
            await service.create(user.id, "anthropic", "sk-2", "Anthropic Key")
            await service.create(user.id, "google", "key-3", "Google Key")

            keys = await service.get_all_for_user(user.id)
            assert len(keys) == 3

    @pytest.mark.asyncio
    async def test_get_by_provider(self, test_db):
        """Get provider keys filtered by provider."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            await service.create(user.id, "openai", "sk-1", "OpenAI 1")
            await service.create(user.id, "openai", "sk-2", "OpenAI 2")
            await service.create(user.id, "anthropic", "sk-3", "Anthropic")

            openai_keys = await service.get_by_provider(user.id, "openai")
            assert len(openai_keys) == 2

            anthropic_keys = await service.get_by_provider(user.id, "anthropic")
            assert len(anthropic_keys) == 1

    @pytest.mark.asyncio
    async def test_get_default_for_provider(self, test_db):
        """Get the default key for a provider."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            key1 = await service.create(user.id, "openai", "sk-1", "First Key")
            await service.create(user.id, "openai", "sk-2", "Second Key")

            default = await service.get_default_for_provider(user.id, "openai")
            assert default is not None
            assert default.id == key1.id  # First key is default

    @pytest.mark.asyncio
    async def test_get_default_fallback(self, test_db):
        """Get first key if no default is explicitly set."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            # Manually create a key without default flag
            provider_key = ProviderKey(
                user_id=user.id,
                provider="openai",
                encrypted_key="encrypted",
                name="Manual Key",
                is_default=False,
            )
            session.add(provider_key)
            await session.commit()
            await session.refresh(provider_key)

            service = ProviderKeyService(session)
            default = await service.get_default_for_provider(user.id, "openai")
            assert default is not None
            assert default.id == provider_key.id


class TestProviderKeyServiceUpdate:
    """Test provider key updates."""

    @pytest.mark.asyncio
    async def test_update_name(self, test_db):
        """Update provider key name."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            created = await service.create(user.id, "openai", "sk-test", "Old Name")

            updated = await service.update(
                created.id,
                user.id,
                name="New Name",
            )

            assert updated is not None
            assert updated.name == "New Name"

    @pytest.mark.asyncio
    async def test_update_account_info(self, test_db):
        """Update account metadata."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            created = await service.create(user.id, "openai", "sk-test", "Key")

            updated = await service.update(
                created.id,
                user.id,
                account_email="new@email.com",
                account_phone="+1-555-0000",
            )

            assert updated.account_email == "new@email.com"
            assert updated.account_phone == "+1-555-0000"

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, test_db):
        """Update nonexistent key returns None."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            result = await service.update(
                "nonexistent-id",
                user.id,
                name="New Name",
            )
            assert result is None


class TestProviderKeyServiceDefault:
    """Test default key management."""

    @pytest.mark.asyncio
    async def test_set_default(self, test_db):
        """Set a key as default."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            key1 = await service.create(user.id, "openai", "sk-1", "Key 1")
            key2 = await service.create(user.id, "openai", "sk-2", "Key 2")

            # Key1 should be default initially
            assert key1.is_default is True
            assert key2.is_default is False

            # Set key2 as default
            result = await service.set_default(key2.id, user.id)
            assert result is True

            # Refresh to see changes
            await session.refresh(key1)
            await session.refresh(key2)

            assert key1.is_default is False
            assert key2.is_default is True

    @pytest.mark.asyncio
    async def test_set_default_nonexistent(self, test_db):
        """Set default on nonexistent key returns False."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            result = await service.set_default("nonexistent-id", user.id)
            assert result is False


class TestProviderKeyServiceDelete:
    """Test provider key deletion."""

    @pytest.mark.asyncio
    async def test_delete_key(self, test_db):
        """Delete a provider key."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            created = await service.create(user.id, "openai", "sk-test", "To Delete")

            result = await service.delete(created.id, user.id)
            assert result is True

            # Verify it's gone
            found = await service.get_by_id(created.id, user.id)
            assert found is None

    @pytest.mark.asyncio
    async def test_delete_default_promotes_next(self, test_db):
        """Deleting default key promotes another to default."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            key1 = await service.create(user.id, "openai", "sk-1", "Key 1")
            key2 = await service.create(user.id, "openai", "sk-2", "Key 2")

            # Delete key1 (the default)
            await service.delete(key1.id, user.id)

            # Key2 should now be default
            await session.refresh(key2)
            assert key2.is_default is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, test_db):
        """Delete nonexistent key returns False."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            result = await service.delete("nonexistent-id", user.id)
            assert result is False


class TestProviderKeyServiceDecrypt:
    """Test key decryption."""

    @pytest.mark.asyncio
    async def test_decrypt_key(self, test_db):
        """Decrypt returns the original key."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            original_key = "sk-test-secret-key-12345"
            service = ProviderKeyService(session)
            created = await service.create(
                user.id, "openai", original_key, "Secret Key"
            )

            decrypted = await service.decrypt_key(created.id, user.id)
            assert decrypted == original_key

    @pytest.mark.asyncio
    async def test_decrypt_nonexistent(self, test_db):
        """Decrypt nonexistent key returns None."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            result = await service.decrypt_key("nonexistent-id", user.id)
            assert result is None


class TestProviderKeyServiceNameExists:
    """Test name existence checking."""

    @pytest.mark.asyncio
    async def test_name_exists_true(self, test_db):
        """Returns True when key with name exists."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            await service.create(user.id, "openai", "sk-test", "Unique Name")

            exists = await service.name_exists(user.id, "openai", "Unique Name")
            assert exists is True

    @pytest.mark.asyncio
    async def test_name_exists_false(self, test_db):
        """Returns False when no key with name exists."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            exists = await service.name_exists(user.id, "openai", "Nonexistent")
            assert exists is False

    @pytest.mark.asyncio
    async def test_name_exists_different_provider(self, test_db):
        """Same name on different provider is allowed."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = ProviderKeyService(session)
            await service.create(user.id, "openai", "sk-test", "My Key")

            # Same name on different provider should not exist
            exists = await service.name_exists(user.id, "anthropic", "My Key")
            assert exists is False


class TestProviderKeyServiceGroupSupport:
    """Test group-based provider key functionality."""

    @pytest.mark.asyncio
    async def test_create_provider_key_with_group(self, test_db):
        """Create a provider key with group_id."""
        from app.models import Organization, Group

        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group = Group(
                organization_id=org.id,
                name="Engineering",
                created_by_id=user.id
            )
            session.add(group)
            await session.commit()
            await session.refresh(group)

            service = ProviderKeyService(session)
            provider_key = await service.create(
                user_id=user.id,
                provider="openai",
                key="sk-test-key-12345",
                name="Team OpenAI Key",
                group_id=group.id,
            )

            assert provider_key is not None
            assert provider_key.group_id == group.id
            assert provider_key.name == "Team OpenAI Key"
            assert provider_key.is_default is True

    @pytest.mark.asyncio
    async def test_get_all_for_group(self, test_db):
        """Get all provider keys for a specific group."""
        from app.models import Organization, Group

        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group = Group(
                organization_id=org.id,
                name="Engineering",
                created_by_id=user.id
            )
            session.add(group)
            await session.commit()
            await session.refresh(group)

            service = ProviderKeyService(session)
            # Create keys in group
            await service.create(user.id, "openai", "sk-1", "OpenAI Key", group_id=group.id)
            await service.create(user.id, "anthropic", "sk-2", "Anthropic Key", group_id=group.id)
            # Create personal key (no group)
            await service.create(user.id, "openai", "sk-3", "Personal Key")

            group_keys = await service.get_all_for_group(group.id)
            assert len(group_keys) == 2

            all_keys = await service.get_all_for_user(user.id)
            assert len(all_keys) == 3

    @pytest.mark.asyncio
    async def test_get_by_id_with_group_filter(self, test_db):
        """Get provider key by ID with group filter."""
        from app.models import Organization, Group

        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group1 = Group(organization_id=org.id, name="Group 1", created_by_id=user.id)
            group2 = Group(organization_id=org.id, name="Group 2", created_by_id=user.id)
            session.add(group1)
            session.add(group2)
            await session.commit()
            await session.refresh(group1)
            await session.refresh(group2)

            service = ProviderKeyService(session)
            key1 = await service.create(user.id, "openai", "sk-1", "Key 1", group_id=group1.id)

            # Can find with correct group
            found = await service.get_by_id(key1.id, user_id=user.id, group_id=group1.id)
            assert found is not None
            assert found.id == key1.id

            # Cannot find with wrong group
            not_found = await service.get_by_id(key1.id, user_id=user.id, group_id=group2.id)
            assert not_found is None

    @pytest.mark.asyncio
    async def test_name_exists_scoped_to_group(self, test_db):
        """Name uniqueness is scoped to group."""
        from app.models import Organization, Group

        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group1 = Group(organization_id=org.id, name="Group 1", created_by_id=user.id)
            group2 = Group(organization_id=org.id, name="Group 2", created_by_id=user.id)
            session.add(group1)
            session.add(group2)
            await session.commit()
            await session.refresh(group1)
            await session.refresh(group2)

            service = ProviderKeyService(session)
            await service.create(user.id, "openai", "sk-1", "Production Key", group_id=group1.id)

            # Same name in same group exists
            exists = await service.name_exists(user.id, "openai", "Production Key", group_id=group1.id)
            assert exists is True

            # Same name in different group does not exist
            exists_other = await service.name_exists(user.id, "openai", "Production Key", group_id=group2.id)
            assert exists_other is False

    @pytest.mark.asyncio
    async def test_get_all_for_user_filtered_by_group(self, test_db):
        """Get all provider keys for user filtered by group_id."""
        from app.models import Organization, Group

        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group = Group(organization_id=org.id, name="Engineering", created_by_id=user.id)
            session.add(group)
            await session.commit()
            await session.refresh(group)

            service = ProviderKeyService(session)
            await service.create(user.id, "openai", "sk-1", "Group Key", group_id=group.id)
            await service.create(user.id, "openai", "sk-2", "Personal Key")

            # Get only group keys
            group_keys = await service.get_all_for_user(user.id, group_id=group.id)
            assert len(group_keys) == 1
            assert group_keys[0].name == "Group Key"

    @pytest.mark.asyncio
    async def test_default_key_is_group_scoped(self, test_db):
        """Default key selection is scoped to group."""
        from app.models import Organization, Group

        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group = Group(organization_id=org.id, name="Engineering", created_by_id=user.id)
            session.add(group)
            await session.commit()
            await session.refresh(group)

            service = ProviderKeyService(session)
            # Create personal default
            personal = await service.create(user.id, "openai", "sk-personal", "Personal")
            # Create group default
            group_key = await service.create(user.id, "openai", "sk-group", "Group", group_id=group.id)

            # Both should be default in their respective scopes
            assert personal.is_default is True
            assert group_key.is_default is True

            # Get default for personal (no group)
            personal_default = await service.get_default_for_provider(user.id, "openai")
            assert personal_default.id == personal.id

            # Get default for group
            group_default = await service.get_default_for_provider(user.id, "openai", group_id=group.id)
            assert group_default.id == group_key.id

    @pytest.mark.asyncio
    async def test_set_default_within_group(self, test_db):
        """Setting default clears previous default only within same group."""
        from app.models import Organization, Group

        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group = Group(organization_id=org.id, name="Engineering", created_by_id=user.id)
            session.add(group)
            await session.commit()
            await session.refresh(group)

            service = ProviderKeyService(session)
            key1 = await service.create(user.id, "openai", "sk-1", "Key 1", group_id=group.id)
            key2 = await service.create(user.id, "openai", "sk-2", "Key 2", group_id=group.id)
            personal = await service.create(user.id, "openai", "sk-p", "Personal")

            # Key1 is default in group, personal is default for personal
            assert key1.is_default is True
            assert key2.is_default is False
            assert personal.is_default is True

            # Set key2 as default in group
            await service.set_default(key2.id, user.id)

            await session.refresh(key1)
            await session.refresh(key2)
            await session.refresh(personal)

            # Key2 is now default, key1 is not, personal is unchanged
            assert key1.is_default is False
            assert key2.is_default is True
            assert personal.is_default is True  # Still default for personal scope
