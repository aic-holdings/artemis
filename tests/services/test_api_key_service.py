"""Tests for APIKeyService."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.api_key_service import APIKeyService
from app.models import User, APIKey, ProviderKey


class TestAPIKeyServiceCreate:
    """Test API key creation via service."""

    @pytest.mark.asyncio
    async def test_create_api_key(self, test_db):
        """Create a new API key."""
        async with test_db() as session:
            # Create a user first
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            api_key, full_key = await service.create(user.id, "Test Key")

            assert api_key is not None
            assert api_key.name == "Test Key"
            assert api_key.user_id == user.id
            assert full_key.startswith("art_")
            assert api_key.key_prefix == full_key[:12]

    @pytest.mark.asyncio
    async def test_create_api_key_default_name(self, test_db):
        """Create an API key with default name."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            api_key, _ = await service.create(user.id)

            assert api_key.name == "Default"

    @pytest.mark.asyncio
    async def test_create_api_key_whitespace_name(self, test_db):
        """Whitespace name becomes Default."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            api_key, _ = await service.create(user.id, "   ")

            assert api_key.name == "Default"


class TestAPIKeyServiceGet:
    """Test API key retrieval."""

    @pytest.mark.asyncio
    async def test_get_by_id(self, test_db):
        """Get API key by ID."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            api_key, _ = await service.create(user.id, "My Key")

            found = await service.get_by_id(api_key.id, user.id)
            assert found is not None
            assert found.id == api_key.id
            assert found.name == "My Key"

    @pytest.mark.asyncio
    async def test_get_by_id_wrong_user(self, test_db):
        """Cannot get API key for different user."""
        async with test_db() as session:
            user1 = User(email="user1@example.com", password_hash="hash123")
            user2 = User(email="user2@example.com", password_hash="hash456")
            session.add(user1)
            session.add(user2)
            await session.commit()
            await session.refresh(user1)
            await session.refresh(user2)

            service = APIKeyService(session)
            api_key, _ = await service.create(user1.id, "User1 Key")

            # User2 cannot access User1's key
            found = await service.get_by_id(api_key.id, user2.id)
            assert found is None

    @pytest.mark.asyncio
    async def test_get_all_for_user(self, test_db):
        """Get all API keys for a user."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            await service.create(user.id, "Key 1")
            await service.create(user.id, "Key 2")
            await service.create(user.id, "Key 3")

            keys = await service.get_all_for_user(user.id)
            assert len(keys) == 3

    @pytest.mark.asyncio
    async def test_get_active_for_user_excludes_revoked(self, test_db):
        """Get active keys excludes revoked ones."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            key1, _ = await service.create(user.id, "Active Key")
            key2, _ = await service.create(user.id, "Revoked Key")

            await service.revoke(key2.id, user.id)

            active_keys = await service.get_active_for_user(user.id)
            assert len(active_keys) == 1
            assert active_keys[0].name == "Active Key"


class TestAPIKeyServiceRevoke:
    """Test API key revocation."""

    @pytest.mark.asyncio
    async def test_revoke_api_key(self, test_db):
        """Revoke an API key."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            api_key, _ = await service.create(user.id, "To Revoke")

            result = await service.revoke(api_key.id, user.id)
            assert result is True

            # Refresh to get updated state
            await session.refresh(api_key)
            assert api_key.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self, test_db):
        """Revoking nonexistent key returns False."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            result = await service.revoke("nonexistent-id", user.id)
            assert result is False


class TestAPIKeyServiceReveal:
    """Test API key reveal (decryption)."""

    @pytest.mark.asyncio
    async def test_reveal_api_key(self, test_db):
        """Reveal returns the original key."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            api_key, original_key = await service.create(user.id, "Secret Key")

            revealed = await service.reveal(api_key.id, user.id)
            assert revealed == original_key

    @pytest.mark.asyncio
    async def test_reveal_nonexistent_key(self, test_db):
        """Revealing nonexistent key returns None."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            revealed = await service.reveal("nonexistent-id", user.id)
            assert revealed is None


class TestAPIKeyServiceNameExists:
    """Test duplicate name checking."""

    @pytest.mark.asyncio
    async def test_name_exists_true(self, test_db):
        """Returns True when active key with name exists."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            await service.create(user.id, "Unique Name")

            exists = await service.name_exists(user.id, "Unique Name")
            assert exists is True

    @pytest.mark.asyncio
    async def test_name_exists_false(self, test_db):
        """Returns False when no key with name exists."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)

            exists = await service.name_exists(user.id, "Nonexistent")
            assert exists is False

    @pytest.mark.asyncio
    async def test_name_exists_ignores_revoked(self, test_db):
        """Revoked keys don't count for name existence."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            service = APIKeyService(session)
            api_key, _ = await service.create(user.id, "Reusable Name")
            await service.revoke(api_key.id, user.id)

            exists = await service.name_exists(user.id, "Reusable Name")
            assert exists is False


class TestAPIKeyServiceProviderOverrides:
    """Test provider key overrides."""

    @pytest.mark.asyncio
    async def test_update_provider_overrides(self, test_db):
        """Can set provider key overrides."""
        from app.models import Organization, Group, ProviderAccount, Provider

        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            # Create the full hierarchy for provider key
            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group = Group(organization_id=org.id, name="Default", created_by_id=user.id)
            session.add(group)
            await session.commit()
            await session.refresh(group)

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

            # Create a provider key
            provider_key = ProviderKey(
                provider_account_id=account.id,
                user_id=user.id,
                encrypted_key="encrypted_value",
                name="My OpenAI Key",
            )
            session.add(provider_key)
            await session.commit()
            await session.refresh(provider_key)

            service = APIKeyService(session)
            api_key, _ = await service.create(user.id, "With Override")

            result = await service.update_provider_overrides(
                api_key.id,
                user.id,
                {"openai": provider_key.id}
            )
            assert result is True

            # Refresh and verify
            await session.refresh(api_key)
            assert api_key.provider_key_overrides is not None
            assert api_key.provider_key_overrides.get("openai") == provider_key.id

    @pytest.mark.asyncio
    async def test_update_provider_overrides_validates_ownership(self, test_db):
        """Overrides must reference keys owned by the user."""
        from app.models import Organization, Group, ProviderAccount, Provider

        async with test_db() as session:
            user1 = User(email="user1@example.com", password_hash="hash123")
            user2 = User(email="user2@example.com", password_hash="hash456")
            session.add(user1)
            session.add(user2)
            await session.commit()
            await session.refresh(user1)
            await session.refresh(user2)

            # Create the full hierarchy for user2's provider key
            org = Organization(name="Test Org", owner_id=user2.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group = Group(organization_id=org.id, name="Default", created_by_id=user2.id)
            session.add(group)
            await session.commit()
            await session.refresh(group)

            provider = Provider(id="openai", name="OpenAI")
            session.add(provider)
            await session.commit()

            account = ProviderAccount(
                group_id=group.id,
                provider_id="openai",
                name="Default Account",
                created_by_id=user2.id
            )
            session.add(account)
            await session.commit()
            await session.refresh(account)

            # Create a provider key for user2
            provider_key = ProviderKey(
                provider_account_id=account.id,
                user_id=user2.id,
                encrypted_key="encrypted_value",
                name="User2 Key",
            )
            session.add(provider_key)
            await session.commit()
            await session.refresh(provider_key)

            service = APIKeyService(session)
            api_key, _ = await service.create(user1.id, "User1 API Key")

            # Try to set override to user2's provider key
            result = await service.update_provider_overrides(
                api_key.id,
                user1.id,
                {"openai": provider_key.id}  # This belongs to user2
            )
            assert result is True

            # Refresh and verify - should be empty since key wasn't owned by user1
            await session.refresh(api_key)
            assert api_key.provider_key_overrides is None


class TestAPIKeyServiceGroupSupport:
    """Test group-based API key functionality."""

    @pytest.mark.asyncio
    async def test_create_api_key_with_group(self, test_db):
        """Create an API key with a group_id."""
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
                created_by_id=user.id,
            )
            session.add(group)
            await session.commit()
            await session.refresh(group)

            service = APIKeyService(session)
            api_key, _ = await service.create(user.id, "Group Key", group_id=group.id)

            assert api_key.group_id == group.id

    @pytest.mark.asyncio
    async def test_get_all_for_group(self, test_db):
        """Get all API keys for a specific group."""
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

            service = APIKeyService(session)
            await service.create(user.id, "G1 Key 1", group_id=group1.id)
            await service.create(user.id, "G1 Key 2", group_id=group1.id)
            await service.create(user.id, "G2 Key 1", group_id=group2.id)
            await service.create(user.id, "Personal Key")  # No group

            group1_keys = await service.get_all_for_group(group1.id)
            group2_keys = await service.get_all_for_group(group2.id)

            assert len(group1_keys) == 2
            assert len(group2_keys) == 1
            assert all(k.group_id == group1.id for k in group1_keys)

    @pytest.mark.asyncio
    async def test_get_by_id_with_group_filter(self, test_db):
        """Get API key by ID filtered by group."""
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

            service = APIKeyService(session)
            api_key, _ = await service.create(user.id, "G1 Key", group_id=group1.id)

            # Can find with correct group
            found = await service.get_by_id(api_key.id, user_id=user.id, group_id=group1.id)
            assert found is not None

            # Cannot find with wrong group
            not_found = await service.get_by_id(api_key.id, user_id=user.id, group_id=group2.id)
            assert not_found is None

    @pytest.mark.asyncio
    async def test_name_exists_scoped_to_group(self, test_db):
        """Duplicate name check is scoped to group."""
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

            service = APIKeyService(session)
            await service.create(user.id, "Production", group_id=group1.id)

            # Same name exists in group1
            exists_in_g1 = await service.name_exists(user.id, "Production", group_id=group1.id)
            assert exists_in_g1 is True

            # Same name does NOT exist in group2
            exists_in_g2 = await service.name_exists(user.id, "Production", group_id=group2.id)
            assert exists_in_g2 is False

    @pytest.mark.asyncio
    async def test_get_all_for_user_filtered_by_group(self, test_db):
        """get_all_for_user can filter by group_id."""
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

            group = Group(organization_id=org.id, name="Team", created_by_id=user.id)
            session.add(group)
            await session.commit()
            await session.refresh(group)

            service = APIKeyService(session)
            await service.create(user.id, "Group Key", group_id=group.id)
            await service.create(user.id, "Personal Key")  # No group

            # Get only group keys
            group_keys = await service.get_all_for_user(user.id, group_id=group.id)
            assert len(group_keys) == 1
            assert group_keys[0].name == "Group Key"

            # Get only personal keys (group_id=None filter)
            all_keys = await service.get_all_for_user(user.id)
            assert len(all_keys) == 2
