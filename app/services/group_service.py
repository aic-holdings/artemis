"""
Group service - handles Group CRUD operations.
"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Group, GroupMember


class GroupService:
    """Service for managing groups within organizations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, group_id: str) -> Optional[Group]:
        """Get a group by ID."""
        result = await self.db.execute(
            select(Group).where(Group.id == group_id)
        )
        return result.scalar_one_or_none()

    async def get_all_for_org(self, org_id: str) -> list[Group]:
        """Get all groups for an organization."""
        result = await self.db.execute(
            select(Group)
            .where(Group.organization_id == org_id)
            .order_by(Group.is_default.desc(), Group.name)  # Default first
        )
        return list(result.scalars().all())

    async def get_default_for_org(self, org_id: str) -> Optional[Group]:
        """Get the default group for an organization."""
        result = await self.db.execute(
            select(Group).where(
                Group.organization_id == org_id,
                Group.is_default == True
            )
        )
        return result.scalar_one_or_none()

    async def name_exists_in_org(self, org_id: str, name: str) -> bool:
        """Check if a group with this name already exists in the organization."""
        result = await self.db.execute(
            select(Group).where(
                Group.organization_id == org_id,
                Group.name == name
            )
        )
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        org_id: str,
        name: str,
        created_by_id: str,
        description: Optional[str] = None,
        is_default: bool = False
    ) -> Group:
        """
        Create a new group.

        Args:
            org_id: Organization ID
            name: Group name
            created_by_id: User ID of creator
            description: Optional description
            is_default: Whether this is the default group for the org

        Returns:
            The created Group object
        """
        name = name.strip()

        # If setting this as default, unset any existing default
        if is_default:
            await self._clear_default_for_org(org_id)

        group = Group(
            organization_id=org_id,
            name=name,
            description=description,
            is_default=is_default,
            created_by_id=created_by_id,
        )
        self.db.add(group)
        await self.db.commit()
        await self.db.refresh(group)

        return group

    async def update(
        self,
        group_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[Group]:
        """
        Update a group's name and/or description.

        Returns:
            Updated Group or None if not found.
        """
        group = await self.get_by_id(group_id)
        if not group:
            return None

        if name is not None:
            group.name = name.strip()
        if description is not None:
            group.description = description

        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def set_default(self, group_id: str) -> Optional[Group]:
        """
        Set a group as the default for its organization.

        Returns:
            Updated Group or None if not found.
        """
        group = await self.get_by_id(group_id)
        if not group:
            return None

        # Clear existing default in this org
        await self._clear_default_for_org(group.organization_id)

        group.is_default = True
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def delete(self, group_id: str) -> tuple[bool, str]:
        """
        Delete a group.

        Returns:
            Tuple of (success, message).
            Cannot delete the default group.
        """
        group = await self.get_by_id(group_id)
        if not group:
            return False, "Group not found"

        if group.is_default:
            return False, "Cannot delete the default group"

        await self.db.delete(group)
        await self.db.commit()
        return True, "Group deleted"

    async def _clear_default_for_org(self, org_id: str) -> None:
        """Clear the default flag for all groups in an organization."""
        result = await self.db.execute(
            select(Group).where(
                Group.organization_id == org_id,
                Group.is_default == True
            )
        )
        for group in result.scalars().all():
            group.is_default = False
        await self.db.commit()
