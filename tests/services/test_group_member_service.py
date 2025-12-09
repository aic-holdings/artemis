"""Tests for GroupMemberService."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.group_member_service import GroupMemberService
from app.services.group_service import GroupService
from app.models import User, Organization, Group, GroupMember


class TestGroupMemberServiceAddMember:
    """Test adding members to groups."""

    @pytest.mark.asyncio
    async def test_add_member(self, test_db):
        """Add a member to a group."""
        async with test_db() as session:
            user = User(email="owner@example.com", password_hash="hash123")
            member = User(email="member@example.com", password_hash="hash456")
            session.add(user)
            session.add(member)
            await session.commit()
            await session.refresh(user)
            await session.refresh(member)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", user.id)

            member_service = GroupMemberService(session)
            result, message = await member_service.add_member(
                group_id=group.id,
                user_id=member.id,
                role="member",
                added_by_id=user.id
            )

            assert result is not None
            assert "success" in message.lower()
            assert result.group_id == group.id
            assert result.user_id == member.id
            assert result.role == "member"
            assert result.added_by_id == user.id

    @pytest.mark.asyncio
    async def test_add_member_as_admin(self, test_db):
        """Add a member with admin role."""
        async with test_db() as session:
            user = User(email="owner@example.com", password_hash="hash123")
            admin = User(email="admin@example.com", password_hash="hash456")
            session.add(user)
            session.add(admin)
            await session.commit()
            await session.refresh(user)
            await session.refresh(admin)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", user.id)

            member_service = GroupMemberService(session)
            result, _ = await member_service.add_member(
                group_id=group.id,
                user_id=admin.id,
                role="admin"
            )

            assert result.role == "admin"

    @pytest.mark.asyncio
    async def test_add_member_already_exists(self, test_db):
        """Cannot add a user who is already a member."""
        async with test_db() as session:
            user = User(email="owner@example.com", password_hash="hash123")
            member = User(email="member@example.com", password_hash="hash456")
            session.add(user)
            session.add(member)
            await session.commit()
            await session.refresh(user)
            await session.refresh(member)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", user.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, member.id, "member")

            # Try to add again
            result, message = await member_service.add_member(group.id, member.id, "admin")

            assert result is None
            assert "already" in message.lower()

    @pytest.mark.asyncio
    async def test_add_member_invalid_role(self, test_db):
        """Cannot add member with invalid role."""
        async with test_db() as session:
            user = User(email="owner@example.com", password_hash="hash123")
            member = User(email="member@example.com", password_hash="hash456")
            session.add(user)
            session.add(member)
            await session.commit()
            await session.refresh(user)
            await session.refresh(member)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", user.id)

            member_service = GroupMemberService(session)
            result, message = await member_service.add_member(
                group.id, member.id, "superuser"
            )

            assert result is None
            assert "invalid role" in message.lower()


class TestGroupMemberServiceGetMember:
    """Test membership queries."""

    @pytest.mark.asyncio
    async def test_is_member_true(self, test_db):
        """Returns True when user is a member."""
        async with test_db() as session:
            user = User(email="user@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", user.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, user.id, "owner")

            is_member = await member_service.is_member(group.id, user.id)
            assert is_member is True

    @pytest.mark.asyncio
    async def test_is_member_false(self, test_db):
        """Returns False when user is not a member."""
        async with test_db() as session:
            user = User(email="user@example.com", password_hash="hash123")
            other = User(email="other@example.com", password_hash="hash456")
            session.add(user)
            session.add(other)
            await session.commit()
            await session.refresh(user)
            await session.refresh(other)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", user.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, user.id, "owner")

            is_member = await member_service.is_member(group.id, other.id)
            assert is_member is False

    @pytest.mark.asyncio
    async def test_get_role(self, test_db):
        """Get user's role in a group."""
        async with test_db() as session:
            owner = User(email="owner@example.com", password_hash="hash123")
            admin = User(email="admin@example.com", password_hash="hash456")
            member = User(email="member@example.com", password_hash="hash789")
            session.add(owner)
            session.add(admin)
            session.add(member)
            await session.commit()
            await session.refresh(owner)
            await session.refresh(admin)
            await session.refresh(member)

            org = Organization(name="Test Org", owner_id=owner.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", owner.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, owner.id, "owner")
            await member_service.add_member(group.id, admin.id, "admin")
            await member_service.add_member(group.id, member.id, "member")

            assert await member_service.get_role(group.id, owner.id) == "owner"
            assert await member_service.get_role(group.id, admin.id) == "admin"
            assert await member_service.get_role(group.id, member.id) == "member"

    @pytest.mark.asyncio
    async def test_get_role_not_member(self, test_db):
        """Returns None when user is not a member."""
        async with test_db() as session:
            user = User(email="user@example.com", password_hash="hash123")
            other = User(email="other@example.com", password_hash="hash456")
            session.add(user)
            session.add(other)
            await session.commit()
            await session.refresh(user)
            await session.refresh(other)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", user.id)

            member_service = GroupMemberService(session)
            role = await member_service.get_role(group.id, other.id)
            assert role is None

    @pytest.mark.asyncio
    async def test_get_members(self, test_db):
        """Get all members of a group."""
        async with test_db() as session:
            owner = User(email="owner@example.com", password_hash="hash123")
            member1 = User(email="member1@example.com", password_hash="hash456")
            member2 = User(email="member2@example.com", password_hash="hash789")
            session.add(owner)
            session.add(member1)
            session.add(member2)
            await session.commit()
            await session.refresh(owner)
            await session.refresh(member1)
            await session.refresh(member2)

            org = Organization(name="Test Org", owner_id=owner.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", owner.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, owner.id, "owner")
            await member_service.add_member(group.id, member1.id, "member")
            await member_service.add_member(group.id, member2.id, "admin")

            members = await member_service.get_members(group.id)
            assert len(members) == 3

    @pytest.mark.asyncio
    async def test_get_user_groups(self, test_db):
        """Get all groups a user belongs to."""
        async with test_db() as session:
            user = User(email="user@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group1 = await group_service.create(org.id, "Team A", user.id)
            group2 = await group_service.create(org.id, "Team B", user.id)
            await group_service.create(org.id, "Team C", user.id)  # Not a member

            member_service = GroupMemberService(session)
            await member_service.add_member(group1.id, user.id, "owner")
            await member_service.add_member(group2.id, user.id, "member")

            groups = await member_service.get_user_groups(user.id)
            assert len(groups) == 2


class TestGroupMemberServiceUpdateRole:
    """Test role updates."""

    @pytest.mark.asyncio
    async def test_update_role(self, test_db):
        """Update a member's role."""
        async with test_db() as session:
            user = User(email="user@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", user.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, user.id, "member")

            result, message = await member_service.update_role(group.id, user.id, "admin")

            assert result is not None
            assert result.role == "admin"
            assert "success" in message.lower()

    @pytest.mark.asyncio
    async def test_update_role_not_member(self, test_db):
        """Cannot update role for non-member."""
        async with test_db() as session:
            user = User(email="user@example.com", password_hash="hash123")
            other = User(email="other@example.com", password_hash="hash456")
            session.add(user)
            session.add(other)
            await session.commit()
            await session.refresh(user)
            await session.refresh(other)

            org = Organization(name="Test Org", owner_id=user.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", user.id)

            member_service = GroupMemberService(session)
            result, message = await member_service.update_role(group.id, other.id, "admin")

            assert result is None
            assert "not a member" in message.lower()


class TestGroupMemberServiceRemoveMember:
    """Test removing members."""

    @pytest.mark.asyncio
    async def test_remove_member(self, test_db):
        """Remove a member from a group."""
        async with test_db() as session:
            owner = User(email="owner@example.com", password_hash="hash123")
            member = User(email="member@example.com", password_hash="hash456")
            session.add(owner)
            session.add(member)
            await session.commit()
            await session.refresh(owner)
            await session.refresh(member)

            org = Organization(name="Test Org", owner_id=owner.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", owner.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, owner.id, "owner")
            await member_service.add_member(group.id, member.id, "member")

            success, message = await member_service.remove_member(group.id, member.id)

            assert success is True
            assert await member_service.is_member(group.id, member.id) is False

    @pytest.mark.asyncio
    async def test_remove_last_owner_fails(self, test_db):
        """Cannot remove the last owner."""
        async with test_db() as session:
            owner = User(email="owner@example.com", password_hash="hash123")
            session.add(owner)
            await session.commit()
            await session.refresh(owner)

            org = Organization(name="Test Org", owner_id=owner.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", owner.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, owner.id, "owner")

            success, message = await member_service.remove_member(group.id, owner.id)

            assert success is False
            assert "last owner" in message.lower()

    @pytest.mark.asyncio
    async def test_remove_one_of_multiple_owners(self, test_db):
        """Can remove an owner if there are multiple."""
        async with test_db() as session:
            owner1 = User(email="owner1@example.com", password_hash="hash123")
            owner2 = User(email="owner2@example.com", password_hash="hash456")
            session.add(owner1)
            session.add(owner2)
            await session.commit()
            await session.refresh(owner1)
            await session.refresh(owner2)

            org = Organization(name="Test Org", owner_id=owner1.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", owner1.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, owner1.id, "owner")
            await member_service.add_member(group.id, owner2.id, "owner")

            success, _ = await member_service.remove_member(group.id, owner1.id)

            assert success is True


class TestGroupMemberServicePermissions:
    """Test permission checking."""

    @pytest.mark.asyncio
    async def test_can_manage_members_owner(self, test_db):
        """Owners can manage members."""
        async with test_db() as session:
            owner = User(email="owner@example.com", password_hash="hash123")
            session.add(owner)
            await session.commit()
            await session.refresh(owner)

            org = Organization(name="Test Org", owner_id=owner.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", owner.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, owner.id, "owner")

            can_manage = await member_service.can_manage_members(group.id, owner.id)
            assert can_manage is True

    @pytest.mark.asyncio
    async def test_can_manage_members_admin(self, test_db):
        """Admins can manage members."""
        async with test_db() as session:
            admin = User(email="admin@example.com", password_hash="hash123")
            session.add(admin)
            await session.commit()
            await session.refresh(admin)

            org = Organization(name="Test Org", owner_id=admin.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", admin.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, admin.id, "admin")

            can_manage = await member_service.can_manage_members(group.id, admin.id)
            assert can_manage is True

    @pytest.mark.asyncio
    async def test_cannot_manage_members_member(self, test_db):
        """Regular members cannot manage members."""
        async with test_db() as session:
            member = User(email="member@example.com", password_hash="hash123")
            session.add(member)
            await session.commit()
            await session.refresh(member)

            org = Organization(name="Test Org", owner_id=member.id)
            session.add(org)
            await session.commit()
            await session.refresh(org)

            group_service = GroupService(session)
            group = await group_service.create(org.id, "Team", member.id)

            member_service = GroupMemberService(session)
            await member_service.add_member(group.id, member.id, "member")

            can_manage = await member_service.can_manage_members(group.id, member.id)
            assert can_manage is False
