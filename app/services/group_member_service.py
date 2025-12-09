"""
Group member service - handles GroupMember CRUD operations.
"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.models import Group, GroupMember, User


class GroupMemberService:
    """Service for managing group memberships."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_membership(self, group_id: str, user_id: str) -> Optional[GroupMember]:
        """Get a specific group membership."""
        result = await self.db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def is_member(self, group_id: str, user_id: str) -> bool:
        """Check if a user is a member of a group."""
        membership = await self.get_membership(group_id, user_id)
        return membership is not None

    async def get_role(self, group_id: str, user_id: str) -> Optional[str]:
        """Get user's role in a group (owner, admin, member) or None if not a member."""
        membership = await self.get_membership(group_id, user_id)
        return membership.role if membership else None

    async def get_members(self, group_id: str) -> list[GroupMember]:
        """Get all members of a group with user info loaded."""
        result = await self.db.execute(
            select(GroupMember)
            .options(joinedload(GroupMember.user))
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.role, GroupMember.added_at)  # Owners first, then by date
        )
        return list(result.scalars().all())

    async def get_user_groups(self, user_id: str, org_id: Optional[str] = None) -> list[Group]:
        """
        Get all groups a user is a member of.

        Args:
            user_id: The user ID
            org_id: Optional org ID to filter by

        Returns:
            List of Group objects
        """
        query = (
            select(Group)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.user_id == user_id)
        )
        if org_id:
            query = query.where(Group.organization_id == org_id)

        query = query.order_by(Group.is_default.desc(), Group.name)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def add_member(
        self,
        group_id: str,
        user_id: str,
        role: str = "member",
        added_by_id: Optional[str] = None
    ) -> tuple[Optional[GroupMember], str]:
        """
        Add a user to a group.

        Args:
            group_id: The group ID
            user_id: The user ID to add
            role: Role (owner, admin, member)
            added_by_id: User ID of who added them

        Returns:
            Tuple of (GroupMember or None, message)
        """
        # Check if already a member
        existing = await self.get_membership(group_id, user_id)
        if existing:
            return None, "User is already a member of this group"

        # Validate role
        if role not in ("owner", "admin", "member"):
            return None, f"Invalid role: {role}"

        membership = GroupMember(
            group_id=group_id,
            user_id=user_id,
            role=role,
            added_by_id=added_by_id,
        )
        self.db.add(membership)
        await self.db.commit()
        await self.db.refresh(membership)

        return membership, "Member added successfully"

    async def update_role(
        self,
        group_id: str,
        user_id: str,
        new_role: str
    ) -> tuple[Optional[GroupMember], str]:
        """
        Update a member's role in a group.

        Returns:
            Tuple of (updated GroupMember or None, message)
        """
        membership = await self.get_membership(group_id, user_id)
        if not membership:
            return None, "User is not a member of this group"

        # Validate role
        if new_role not in ("owner", "admin", "member"):
            return None, f"Invalid role: {new_role}"

        membership.role = new_role
        await self.db.commit()
        await self.db.refresh(membership)

        return membership, "Role updated successfully"

    async def remove_member(self, group_id: str, user_id: str) -> tuple[bool, str]:
        """
        Remove a user from a group.

        Returns:
            Tuple of (success, message)
        """
        membership = await self.get_membership(group_id, user_id)
        if not membership:
            return False, "User is not a member of this group"

        # Check if this is the last owner
        if membership.role == "owner":
            owners = await self._count_owners(group_id)
            if owners <= 1:
                return False, "Cannot remove the last owner of a group"

        await self.db.delete(membership)
        await self.db.commit()

        return True, "Member removed successfully"

    async def can_manage_members(self, group_id: str, user_id: str) -> bool:
        """Check if a user can manage members (add/remove) in a group."""
        role = await self.get_role(group_id, user_id)
        # Only owners and admins can manage members
        return role in ("owner", "admin")

    async def _count_owners(self, group_id: str) -> int:
        """Count the number of owners in a group."""
        result = await self.db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.role == "owner"
            )
        )
        return len(list(result.scalars().all()))
