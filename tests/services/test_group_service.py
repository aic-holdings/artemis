"""Tests for GroupService."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.group_service import GroupService
from app.models import User, Organization, Group


class TestGroupServiceCreate:
    """Test group creation via service."""

    @pytest.mark.asyncio
    async def test_create_group(self, test_db):
        """Create a new group."""
        async with test_db() as session:
            # Create user and org first
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            group = await service.create(
                org_id=org.id,
                name="Engineering",
                created_by_id=user.id,
                description="Engineering team"
            )

            assert group is not None
            assert group.name == "Engineering"
            assert group.description == "Engineering team"
            assert group.organization_id == org.id
            assert group.created_by_id == user.id
            assert group.is_default is False

    @pytest.mark.asyncio
    async def test_create_group_strips_whitespace(self, test_db):
        """Group name is stripped of whitespace."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            group = await service.create(
                org_id=org.id,
                name="  Spaced Name  ",
                created_by_id=user.id
            )

            assert group.name == "Spaced Name"

    @pytest.mark.asyncio
    async def test_create_default_group(self, test_db):
        """Create a default group."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            group = await service.create(
                org_id=org.id,
                name="Default",
                created_by_id=user.id,
                is_default=True
            )

            assert group.is_default is True

    @pytest.mark.asyncio
    async def test_create_default_clears_existing_default(self, test_db):
        """Creating a new default group clears the old default."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)

            # Create first default group
            group1 = await service.create(
                org_id=org.id,
                name="Group 1",
                created_by_id=user.id,
                is_default=True
            )

            # Create second default group
            group2 = await service.create(
                org_id=org.id,
                name="Group 2",
                created_by_id=user.id,
                is_default=True
            )

            # Refresh group1 to see updated state
            await session.refresh(group1)

            assert group1.is_default is False
            assert group2.is_default is True


class TestGroupServiceGet:
    """Test group retrieval."""

    @pytest.mark.asyncio
    async def test_get_by_id(self, test_db):
        """Get group by ID."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            group = await service.create(org.id, "My Group", user.id)

            found = await service.get_by_id(group.id)
            assert found is not None
            assert found.id == group.id
            assert found.name == "My Group"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, test_db):
        """Get nonexistent group returns None."""
        async with test_db() as session:
            service = GroupService(session)
            found = await service.get_by_id("nonexistent-id")
            assert found is None

    @pytest.mark.asyncio
    async def test_get_all_for_org(self, test_db):
        """Get all groups for an organization."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            await service.create(org.id, "Group A", user.id)
            await service.create(org.id, "Group B", user.id)
            await service.create(org.id, "Default", user.id, is_default=True)

            groups = await service.get_all_for_org(org.id)
            assert len(groups) == 3
            # Default should be first
            assert groups[0].is_default is True

    @pytest.mark.asyncio
    async def test_get_default_for_org(self, test_db):
        """Get the default group for an org."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            await service.create(org.id, "Not Default", user.id)
            default_group = await service.create(org.id, "Default", user.id, is_default=True)

            found = await service.get_default_for_org(org.id)
            assert found is not None
            assert found.id == default_group.id
            assert found.is_default is True

    @pytest.mark.asyncio
    async def test_get_default_for_org_none(self, test_db):
        """Returns None when no default group exists."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            await service.create(org.id, "Not Default", user.id, is_default=False)

            found = await service.get_default_for_org(org.id)
            assert found is None


class TestGroupServiceNameExists:
    """Test duplicate name checking."""

    @pytest.mark.asyncio
    async def test_name_exists_true(self, test_db):
        """Returns True when group with name exists in org."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            await service.create(org.id, "Unique Name", user.id)

            exists = await service.name_exists_in_org(org.id, "Unique Name")
            assert exists is True

    @pytest.mark.asyncio
    async def test_name_exists_false(self, test_db):
        """Returns False when no group with name exists."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)

            exists = await service.name_exists_in_org(org.id, "Nonexistent")
            assert exists is False

    @pytest.mark.asyncio
    async def test_name_exists_different_org(self, test_db):
        """Same name can exist in different orgs."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org1 = Organization(name="Org 1", owner_id=user.id)
            org2 = Organization(name="Org 2", owner_id=user.id)
            session.add(org1)
            session.add(org2)
            await session.commit()
            await session.refresh(org1)
            await session.refresh(org2)

            service = GroupService(session)
            await service.create(org1.id, "Engineering", user.id)

            # Same name in org2 should not exist
            exists = await service.name_exists_in_org(org2.id, "Engineering")
            assert exists is False


class TestGroupServiceUpdate:
    """Test group updates."""

    @pytest.mark.asyncio
    async def test_update_group(self, test_db):
        """Update group name and description."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            group = await service.create(org.id, "Original", user.id)

            updated = await service.update(
                group.id,
                name="Updated Name",
                description="New description"
            )

            assert updated is not None
            assert updated.name == "Updated Name"
            assert updated.description == "New description"

    @pytest.mark.asyncio
    async def test_update_nonexistent_group(self, test_db):
        """Update nonexistent group returns None."""
        async with test_db() as session:
            service = GroupService(session)
            result = await service.update("nonexistent-id", name="New Name")
            assert result is None


class TestGroupServiceSetDefault:
    """Test setting default group."""

    @pytest.mark.asyncio
    async def test_set_default(self, test_db):
        """Set a group as default."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            group1 = await service.create(org.id, "Group 1", user.id, is_default=True)
            group2 = await service.create(org.id, "Group 2", user.id)

            await service.set_default(group2.id)

            await session.refresh(group1)
            await session.refresh(group2)

            assert group1.is_default is False
            assert group2.is_default is True


class TestGroupServiceDelete:
    """Test group deletion."""

    @pytest.mark.asyncio
    async def test_delete_group(self, test_db):
        """Delete a non-default group."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            group = await service.create(org.id, "To Delete", user.id, is_default=False)
            group_id = group.id

            success, message = await service.delete(group_id)

            assert success is True
            assert message == "Group deleted"

            # Verify deleted
            found = await service.get_by_id(group_id)
            assert found is None

    @pytest.mark.asyncio
    async def test_delete_default_group_fails(self, test_db):
        """Cannot delete the default group."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            service = GroupService(session)
            group = await service.create(org.id, "Default", user.id, is_default=True)

            success, message = await service.delete(group.id)

            assert success is False
            assert "default group" in message.lower()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_group(self, test_db):
        """Delete nonexistent group fails."""
        async with test_db() as session:
            service = GroupService(session)
            success, message = await service.delete("nonexistent-id")

            assert success is False
            assert "not found" in message.lower()
