"""Tests for ProviderKeyService."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.provider_key_service import ProviderKeyService
from app.models import User, ProviderKey, Organization, Group, ProviderAccount, Provider
from app.auth import decrypt_api_key


async def create_test_hierarchy(session):
    """Create the full hierarchy needed for provider keys: User → Org → Group → ProviderAccount."""
    user = User(email="test@example.com", password_hash="hash123")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    org = Organization(name="Test Org", owner_id=user.id)
    session.add(org)
    await session.commit()
    await session.refresh(org)

    group = Group(organization_id=org.id, name="Default", created_by_id=user.id)
    session.add(group)
    await session.commit()
    await session.refresh(group)

    # Create provider if it doesn't exist
    from sqlalchemy import select
    result = await session.execute(select(Provider).where(Provider.id == "openai"))
    provider = result.scalar_one_or_none()
    if not provider:
        provider = Provider(id="openai", name="OpenAI")
        session.add(provider)
        await session.commit()

    account = ProviderAccount(
        group_id=group.id,
        provider_id="openai",
        name="Default Account",
        created_by_id=user.id
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)

    return user, org, group, account


async def create_provider_account(session, group_id, provider_id, name, user_id):
    """Create a provider account with provider."""
    from sqlalchemy import select
    result = await session.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        provider = Provider(id=provider_id, name=provider_id.title())
        session.add(provider)
        await session.commit()

    account = ProviderAccount(
        group_id=group_id,
        provider_id=provider_id,
        name=name,
        created_by_id=user_id
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


class TestProviderKeyServiceCreate:
    """Test provider key creation via service."""

    @pytest.mark.asyncio
    async def test_create_provider_key(self, test_db):
        """Create a new provider key."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            provider_key = await service.create(
                provider_account_id=account.id,
                user_id=user.id,
                key="sk-test-key-12345",
                name="My OpenAI Key",
            )

            assert provider_key is not None
            assert provider_key.name == "My OpenAI Key"
            assert provider_key.user_id == user.id
            assert provider_key.provider_account_id == account.id
            assert provider_key.is_default is True  # First key is auto-default

    @pytest.mark.asyncio
    async def test_create_provider_key_with_metadata(self, test_db):
        """Create provider key - metadata is stored on account, not key."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            provider_key = await service.create(
                provider_account_id=account.id,
                user_id=user.id,
                key="sk-ant-12345",
                name="Work Key",
            )

            assert provider_key is not None
            assert provider_key.name == "Work Key"

    @pytest.mark.asyncio
    async def test_first_key_auto_default(self, test_db):
        """First key for a provider is automatically default."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            key1 = await service.create(
                provider_account_id=account.id,
                user_id=user.id,
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
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            await service.create(
                provider_account_id=account.id,
                user_id=user.id,
                key="sk-key1",
                name="Key 1",
            )
            key2 = await service.create(
                provider_account_id=account.id,
                user_id=user.id,
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
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            created = await service.create(
                provider_account_id=account.id,
                user_id=user.id,
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
            user1, org, group, account = await create_test_hierarchy(session)

            user2 = User(email="user2@example.com", password_hash="hash456")
            session.add(user2)
            await session.commit()
            await session.refresh(user2)

            service = ProviderKeyService(session)
            created = await service.create(
                provider_account_id=account.id,
                user_id=user1.id,
                key="sk-test",
                name="User1 Key",
            )

            # User2 cannot access User1's key
            found = await service.get_by_id(created.id, user2.id)
            assert found is None

    @pytest.mark.asyncio
    async def test_get_all_for_user(self, test_db):
        """Get all provider keys created by a user."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            # Create accounts for different providers
            anthropic_account = await create_provider_account(
                session, group.id, "anthropic", "Anthropic Account", user.id
            )
            google_account = await create_provider_account(
                session, group.id, "google", "Google Account", user.id
            )

            service = ProviderKeyService(session)
            await service.create(account.id, user.id, "sk-1", "OpenAI Key")
            await service.create(anthropic_account.id, user.id, "sk-2", "Anthropic Key")
            await service.create(google_account.id, user.id, "key-3", "Google Key")

            keys = await service.get_all_for_user(user.id)
            assert len(keys) == 3

    @pytest.mark.asyncio
    async def test_get_by_provider(self, test_db):
        """Get provider keys filtered by provider."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            anthropic_account = await create_provider_account(
                session, group.id, "anthropic", "Anthropic Account", user.id
            )

            service = ProviderKeyService(session)
            await service.create(account.id, user.id, "sk-1", "OpenAI 1")
            await service.create(account.id, user.id, "sk-2", "OpenAI 2")
            await service.create(anthropic_account.id, user.id, "sk-3", "Anthropic")

            openai_keys = await service.get_all_for_group(group.id, "openai")
            assert len(openai_keys) == 2

            anthropic_keys = await service.get_all_for_group(group.id, "anthropic")
            assert len(anthropic_keys) == 1

    @pytest.mark.asyncio
    async def test_get_default_for_provider(self, test_db):
        """Get the default key for a provider."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            key1 = await service.create(account.id, user.id, "sk-1", "First Key")
            await service.create(account.id, user.id, "sk-2", "Second Key")

            default = await service.get_default_for_provider(group.id, "openai")
            assert default is not None
            assert default.id == key1.id  # First key is default

    @pytest.mark.asyncio
    async def test_get_default_fallback(self, test_db):
        """Get first key if no default is explicitly set."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            # Manually create a key without default flag
            provider_key = ProviderKey(
                provider_account_id=account.id,
                user_id=user.id,
                encrypted_key="encrypted",
                name="Manual Key",
                is_default=False,
            )
            session.add(provider_key)
            await session.commit()
            await session.refresh(provider_key)

            service = ProviderKeyService(session)
            default = await service.get_default_for_provider(group.id, "openai")
            assert default is not None
            assert default.id == provider_key.id


class TestProviderKeyServiceUpdate:
    """Test provider key updates."""

    @pytest.mark.asyncio
    async def test_update_name(self, test_db):
        """Update provider key name."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            created = await service.create(account.id, user.id, "sk-test", "Old Name")

            updated = await service.update(
                created.id,
                user.id,
                name="New Name",
            )

            assert updated is not None
            assert updated.name == "New Name"

    @pytest.mark.asyncio
    async def test_update_account_info(self, test_db):
        """Update key - account info is on ProviderAccount, not key."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            created = await service.create(account.id, user.id, "sk-test", "Key")

            # Can update name
            updated = await service.update(
                created.id,
                user.id,
                name="Updated Key",
            )

            assert updated.name == "Updated Key"

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, test_db):
        """Update nonexistent key returns None."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

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
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            key1 = await service.create(account.id, user.id, "sk-1", "Key 1")
            key2 = await service.create(account.id, user.id, "sk-2", "Key 2")

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
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            result = await service.set_default("nonexistent-id", user.id)
            assert result is False


class TestProviderKeyServiceDelete:
    """Test provider key deletion."""

    @pytest.mark.asyncio
    async def test_delete_key(self, test_db):
        """Delete a provider key."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            created = await service.create(account.id, user.id, "sk-test", "To Delete")

            result = await service.delete(created.id, user.id)
            assert result is True

            # Verify it's gone
            found = await service.get_by_id(created.id, user.id)
            assert found is None

    @pytest.mark.asyncio
    async def test_delete_default_promotes_next(self, test_db):
        """Deleting default key promotes another to default."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            key1 = await service.create(account.id, user.id, "sk-1", "Key 1")
            key2 = await service.create(account.id, user.id, "sk-2", "Key 2")

            # Delete key1 (the default)
            await service.delete(key1.id, user.id)

            # Key2 should now be default
            await session.refresh(key2)
            assert key2.is_default is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, test_db):
        """Delete nonexistent key returns False."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            result = await service.delete("nonexistent-id", user.id)
            assert result is False


class TestProviderKeyServiceDecrypt:
    """Test key decryption."""

    @pytest.mark.asyncio
    async def test_decrypt_key(self, test_db):
        """Decrypt returns the original key."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            original_key = "sk-test-secret-key-12345"
            service = ProviderKeyService(session)
            created = await service.create(
                account.id, user.id, original_key, "Secret Key"
            )

            decrypted = await service.decrypt_key(created.id, user.id)
            assert decrypted == original_key

    @pytest.mark.asyncio
    async def test_decrypt_nonexistent(self, test_db):
        """Decrypt nonexistent key returns None."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            result = await service.decrypt_key("nonexistent-id", user.id)
            assert result is None


class TestProviderKeyServiceNameExists:
    """Test name existence checking."""

    @pytest.mark.asyncio
    async def test_name_exists_true(self, test_db):
        """Returns True when key with name exists."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            await service.create(account.id, user.id, "sk-test", "Unique Name")

            exists = await service.name_exists(account.id, "Unique Name")
            assert exists is True

    @pytest.mark.asyncio
    async def test_name_exists_false(self, test_db):
        """Returns False when no key with name exists."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            exists = await service.name_exists(account.id, "Nonexistent")
            assert exists is False

    @pytest.mark.asyncio
    async def test_name_exists_different_provider(self, test_db):
        """Same name on different provider account is allowed."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            anthropic_account = await create_provider_account(
                session, group.id, "anthropic", "Anthropic Account", user.id
            )

            service = ProviderKeyService(session)
            await service.create(account.id, user.id, "sk-test", "My Key")

            # Same name on different account should not exist
            exists = await service.name_exists(anthropic_account.id, "My Key")
            assert exists is False


class TestProviderKeyServiceGroupSupport:
    """Test group-based provider key functionality."""

    @pytest.mark.asyncio
    async def test_create_provider_key_with_group(self, test_db):
        """Create a provider key with group (via account)."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            provider_key = await service.create(
                provider_account_id=account.id,
                user_id=user.id,
                key="sk-test-key-12345",
                name="Team OpenAI Key",
            )

            assert provider_key is not None
            assert provider_key.provider_account_id == account.id
            assert provider_key.name == "Team OpenAI Key"
            assert provider_key.is_default is True

    @pytest.mark.asyncio
    async def test_get_all_for_group(self, test_db):
        """Get all provider keys for a specific group."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            anthropic_account = await create_provider_account(
                session, group.id, "anthropic", "Anthropic Account", user.id
            )

            service = ProviderKeyService(session)
            # Create keys in group
            await service.create(account.id, user.id, "sk-1", "OpenAI Key")
            await service.create(anthropic_account.id, user.id, "sk-2", "Anthropic Key")

            group_keys = await service.get_all_for_group(group.id)
            assert len(group_keys) == 2

    @pytest.mark.asyncio
    async def test_get_by_id_with_group_filter(self, test_db):
        """Get provider key by ID - group filtering is done via account."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            # Create another group with its own account
            group2 = Group(organization_id=org.id, name="Group 2", created_by_id=user.id)
            session.add(group2)
            await session.commit()
            await session.refresh(group2)

            service = ProviderKeyService(session)
            key1 = await service.create(account.id, user.id, "sk-1", "Key 1")

            # Can find by ID and user
            found = await service.get_by_id(key1.id, user_id=user.id)
            assert found is not None
            assert found.id == key1.id

    @pytest.mark.asyncio
    async def test_name_exists_scoped_to_account(self, test_db):
        """Name uniqueness is scoped to account."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            # Create second account in same group
            account2 = ProviderAccount(
                group_id=group.id,
                provider_id="openai",
                name="Second Account",
                created_by_id=user.id
            )
            session.add(account2)
            await session.commit()
            await session.refresh(account2)

            service = ProviderKeyService(session)
            await service.create(account.id, user.id, "sk-1", "Production Key")

            # Same name in same account exists
            exists = await service.name_exists(account.id, "Production Key")
            assert exists is True

            # Same name in different account does not exist
            exists_other = await service.name_exists(account2.id, "Production Key")
            assert exists_other is False

    @pytest.mark.asyncio
    async def test_get_all_for_user_filtered_by_group(self, test_db):
        """Get all provider keys for user filtered by group_id."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            service = ProviderKeyService(session)
            await service.create(account.id, user.id, "sk-1", "Group Key")

            # Get only group keys
            group_keys = await service.get_all_for_user(user.id, group_id=group.id)
            assert len(group_keys) == 1
            assert group_keys[0].name == "Group Key"

    @pytest.mark.asyncio
    async def test_default_key_is_group_scoped(self, test_db):
        """Default key selection is scoped to group (via accounts)."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            # Create another group with its own account
            group2 = Group(organization_id=org.id, name="Group 2", created_by_id=user.id)
            session.add(group2)
            await session.commit()
            await session.refresh(group2)

            account2 = await create_provider_account(
                session, group2.id, "openai", "Group2 OpenAI", user.id
            )

            service = ProviderKeyService(session)
            # Create key in group 1
            key1 = await service.create(account.id, user.id, "sk-group1", "Group1 Key")
            # Create key in group 2
            key2 = await service.create(account2.id, user.id, "sk-group2", "Group2 Key")

            # Both should be default in their respective groups
            assert key1.is_default is True
            assert key2.is_default is True

            # Get default for group 1
            default1 = await service.get_default_for_provider(group.id, "openai")
            assert default1.id == key1.id

            # Get default for group 2
            default2 = await service.get_default_for_provider(group2.id, "openai")
            assert default2.id == key2.id

    @pytest.mark.asyncio
    async def test_set_default_within_group(self, test_db):
        """Setting default clears previous default only within same group."""
        async with test_db() as session:
            user, org, group, account = await create_test_hierarchy(session)

            # Create another group with its own account
            group2 = Group(organization_id=org.id, name="Group 2", created_by_id=user.id)
            session.add(group2)
            await session.commit()
            await session.refresh(group2)

            account2 = await create_provider_account(
                session, group2.id, "openai", "Group2 OpenAI", user.id
            )

            service = ProviderKeyService(session)
            key1 = await service.create(account.id, user.id, "sk-1", "Key 1")
            key2 = await service.create(account.id, user.id, "sk-2", "Key 2")
            key_other_group = await service.create(account2.id, user.id, "sk-other", "Other Group")

            # Key1 is default in group 1, key_other_group is default in group 2
            assert key1.is_default is True
            assert key2.is_default is False
            assert key_other_group.is_default is True

            # Set key2 as default in group 1
            await service.set_default(key2.id, user.id)

            await session.refresh(key1)
            await session.refresh(key2)
            await session.refresh(key_other_group)

            # Key2 is now default in group 1, key1 is not
            assert key1.is_default is False
            assert key2.is_default is True
            # key_other_group is unchanged (different group)
            assert key_other_group.is_default is True
