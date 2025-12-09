"""
Organization service - handles Organization CRUD operations.
"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Organization, OrganizationMember, Group, GroupMember


class OrganizationService:
    """Service for managing organizations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, org_id: str) -> Optional[Organization]:
        """Get an organization by ID."""
        result = await self.db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[Organization]:
        """Get an organization by name."""
        result = await self.db.execute(
            select(Organization).where(Organization.name == name)
        )
        return result.scalar_one_or_none()

    async def name_exists(self, name: str) -> bool:
        """Check if an organization with this name already exists."""
        org = await self.get_by_name(name)
        return org is not None

    async def create(
        self,
        name: str,
        owner_id: str,
        create_default_group: bool = True
    ) -> tuple[Organization, Optional[Group]]:
        """
        Create a new organization with the user as owner.

        Args:
            name: Organization name (must be unique)
            owner_id: User ID of the owner
            create_default_group: Whether to create a default group

        Returns:
            Tuple of (Organization, default Group or None)

        Raises:
            ValueError: If organization name already exists
        """
        name = name.strip()

        if await self.name_exists(name):
            raise ValueError(f"Organization '{name}' already exists")

        # Create organization
        org = Organization(
            name=name,
            owner_id=owner_id,
        )
        self.db.add(org)
        await self.db.flush()

        # Add owner as organization member with 'owner' role
        membership = OrganizationMember(
            organization_id=org.id,
            user_id=owner_id,
            email="",  # Will be filled from user
            role="owner",
            status="active",
        )
        self.db.add(membership)

        # Create default group if requested
        default_group = None
        if create_default_group:
            default_group = Group(
                organization_id=org.id,
                name="Default",
                description="Default group for all organization members",
                is_default=True,
                created_by_id=owner_id,
            )
            self.db.add(default_group)
            await self.db.flush()

            # Add owner to default group
            group_membership = GroupMember(
                group_id=default_group.id,
                user_id=owner_id,
                role="owner",
            )
            self.db.add(group_membership)

        await self.db.commit()
        await self.db.refresh(org)
        if default_group:
            await self.db.refresh(default_group)

        return org, default_group

    async def update(
        self,
        org_id: str,
        name: Optional[str] = None,
    ) -> Optional[Organization]:
        """
        Update an organization's name.

        Returns:
            Updated Organization or None if not found.
        """
        org = await self.get_by_id(org_id)
        if not org:
            return None

        if name is not None:
            name = name.strip()
            # Check if new name conflicts with existing org
            existing = await self.get_by_name(name)
            if existing and existing.id != org_id:
                raise ValueError(f"Organization '{name}' already exists")
            org.name = name

        await self.db.commit()
        await self.db.refresh(org)
        return org

    async def delete(self, org_id: str) -> tuple[bool, str]:
        """
        Delete an organization.

        Returns:
            Tuple of (success, message).
        """
        org = await self.get_by_id(org_id)
        if not org:
            return False, "Organization not found"

        await self.db.delete(org)
        await self.db.commit()
        return True, "Organization deleted"

    async def get_user_organizations(self, user_id: str) -> list[Organization]:
        """Get all organizations a user is a member of."""
        result = await self.db.execute(
            select(Organization)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.status == "active"
            )
            .order_by(Organization.name)
        )
        return list(result.scalars().all())
