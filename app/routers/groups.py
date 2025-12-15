"""
Group management routes.
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Group, OrganizationMember, utc_now
from app.routers.auth_routes import get_current_user, get_user_organizations, get_user_groups
from app.services.group_service import GroupService
from app.services.group_member_service import GroupMemberService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/groups")
async def groups_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Groups management page - lists groups in current organization."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)

    # Groups are only relevant when viewing an organization
    if not ctx.active_org_id:
        return templates.TemplateResponse(
            request,
            "groups.html",
            {
                "user": user,
                "active_org": None,
                "organizations": organizations,
                "groups": [],
                "user_role": None,
                "error": "Select an organization to manage groups.",
            },
        )

    # Get groups for this org that user is a member of
    groups = await get_user_groups(user.id, ctx.active_org_id, db)

    # Get member counts and user's role in each group
    group_member_service = GroupMemberService(db)
    groups_with_info = []
    user_role = None

    for group in groups:
        members = await group_member_service.get_members(group.id)
        role = await group_member_service.get_role(group.id, user.id)

        # Track user's role in active group
        if ctx.active_group_id and group.id == ctx.active_group_id:
            user_role = role

        groups_with_info.append({
            "group": group,
            "member_count": len(members),
            "members": members,
            "user_role": role,
            "can_manage": role in ("owner", "admin"),
        })

    # Track if we're in "All Groups" mode (org selected but no specific group)
    all_groups_mode = ctx.active_org_id and not ctx.active_group_id

    return templates.TemplateResponse(
        request,
        "groups.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,  # For navbar dropdown
            "groups_with_info": groups_with_info,  # For page content
            "user_role": user_role,
            "all_groups_mode": all_groups_mode,
        },
    )


@router.post("/groups")
async def create_group(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Create a new group in the current organization."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    if not ctx.active_org_id:
        return RedirectResponse(url="/groups?error=no_org", status_code=303)

    # Check user has permission to create groups (must be owner/admin of at least one group)
    group_member_service = GroupMemberService(db)
    user_groups = await get_user_groups(ctx.user.id, ctx.active_org_id, db)

    can_create = False
    for g in user_groups:
        role = await group_member_service.get_role(g.id, ctx.user.id)
        if role in ("owner", "admin"):
            can_create = True
            break

    if not can_create:
        return RedirectResponse(url="/groups?error=no_permission", status_code=303)

    group_service = GroupService(db)

    # Check for duplicate name
    if await group_service.name_exists_in_org(ctx.active_org_id, name.strip()):
        return RedirectResponse(url="/groups?error=duplicate_name", status_code=303)

    # Create the group
    group = await group_service.create(
        org_id=ctx.active_org_id,
        name=name.strip(),
        created_by_id=ctx.user.id,
        description=description.strip() if description else None,
    )

    # Add creator as owner
    await group_member_service.add_member(
        group_id=group.id,
        user_id=ctx.user.id,
        role="owner",
        added_by_id=ctx.user.id,
    )

    return RedirectResponse(url="/groups", status_code=303)


@router.post("/groups/{group_id}/update")
async def update_group(
    group_id: str,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Update a group's name and description."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    group_member_service = GroupMemberService(db)
    group_service = GroupService(db)

    # Verify user is admin/owner of this group
    if not await group_member_service.can_manage_members(group_id, ctx.user.id):
        return RedirectResponse(url="/groups?error=no_permission", status_code=303)

    # Check for duplicate name (excluding current group)
    group = await group_service.get_by_id(group_id)
    if not group:
        return RedirectResponse(url="/groups?error=not_found", status_code=303)

    if name.strip() != group.name and await group_service.name_exists_in_org(
        group.organization_id, name.strip()
    ):
        return RedirectResponse(url="/groups?error=duplicate_name", status_code=303)

    await group_service.update(
        group_id=group_id,
        name=name.strip(),
        description=description.strip() if description else None,
    )

    return RedirectResponse(url="/groups", status_code=303)


@router.post("/groups/{group_id}/delete")
async def delete_group(
    group_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a group."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    group_member_service = GroupMemberService(db)
    group_service = GroupService(db)

    # Verify user is owner of this group
    role = await group_member_service.get_role(group_id, ctx.user.id)
    if role != "owner":
        return RedirectResponse(url="/groups?error=owners_only", status_code=303)

    success, message = await group_service.delete(group_id)
    if not success:
        return RedirectResponse(url=f"/groups?error={message}", status_code=303)

    return RedirectResponse(url="/groups", status_code=303)


@router.post("/groups/{group_id}/members")
async def add_member(
    group_id: str,
    request: Request,
    email: str = Form(...),
    role: str = Form("member"),
    db: AsyncSession = Depends(get_db),
):
    """Add a member to a group."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    group_member_service = GroupMemberService(db)

    # Verify user can manage members
    if not await group_member_service.can_manage_members(group_id, ctx.user.id):
        return RedirectResponse(url="/groups?error=no_permission", status_code=303)

    # Find user by email
    result = await db.execute(select(User).where(User.email == email.strip().lower()))
    target_user = result.scalar_one_or_none()

    if not target_user:
        return RedirectResponse(url="/groups?error=user_not_found", status_code=303)

    # Get the group to find its organization
    group_result = await db.execute(select(Group).where(Group.id == group_id))
    group = group_result.scalar_one_or_none()
    if not group:
        return RedirectResponse(url="/groups?error=group_not_found", status_code=303)

    # Check if user is an active member of the organization
    org_member_result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == group.organization_id,
            OrganizationMember.user_id == target_user.id,
            OrganizationMember.status == "active"
        )
    )
    org_membership = org_member_result.scalar_one_or_none()

    # If not an org member, add them automatically
    if not org_membership:
        new_org_membership = OrganizationMember(
            organization_id=group.organization_id,
            user_id=target_user.id,
            email=target_user.email,
            role="member",
            status="active",
            invited_by_id=ctx.user.id,
            accepted_at=utc_now(),
        )
        db.add(new_org_membership)
        await db.flush()

    # Validate role - only owners can add other owners/admins
    requester_role = await group_member_service.get_role(group_id, ctx.user.id)
    if role in ("owner", "admin") and requester_role != "owner":
        return RedirectResponse(url="/groups?error=owners_only_for_admin", status_code=303)

    # Add the member
    _, message = await group_member_service.add_member(
        group_id=group_id,
        user_id=target_user.id,
        role=role,
        added_by_id=ctx.user.id,
    )

    if "already" in message.lower():
        return RedirectResponse(url="/groups?error=already_member", status_code=303)

    return RedirectResponse(url="/groups", status_code=303)


@router.post("/groups/{group_id}/members/{user_id}/remove")
async def remove_member(
    group_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from a group."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    group_member_service = GroupMemberService(db)

    # Users can remove themselves, otherwise must be admin/owner
    if user_id != ctx.user.id:
        if not await group_member_service.can_manage_members(group_id, ctx.user.id):
            return RedirectResponse(url="/groups?error=no_permission", status_code=303)

    success, message = await group_member_service.remove_member(group_id, user_id)
    if not success:
        error_key = "last_owner" if "last owner" in message.lower() else "remove_failed"
        return RedirectResponse(url=f"/groups?error={error_key}", status_code=303)

    return RedirectResponse(url="/groups", status_code=303)


@router.post("/groups/{group_id}/members/{user_id}/role")
async def update_member_role(
    group_id: str,
    user_id: str,
    request: Request,
    role: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Update a member's role in a group."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    group_member_service = GroupMemberService(db)

    # Only owners can change roles
    requester_role = await group_member_service.get_role(group_id, ctx.user.id)
    if requester_role != "owner":
        return RedirectResponse(url="/groups?error=owners_only", status_code=303)

    # Can't demote yourself if you're the last owner
    if user_id == ctx.user.id and role != "owner":
        owners_count = await group_member_service._count_owners(group_id)
        if owners_count <= 1:
            return RedirectResponse(url="/groups?error=last_owner", status_code=303)

    _, message = await group_member_service.update_role(group_id, user_id, role)

    return RedirectResponse(url="/groups", status_code=303)


@router.post("/groups/{group_id}/set-default")
async def set_default_group(
    group_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Set a group as the default for its organization."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    group_member_service = GroupMemberService(db)
    group_service = GroupService(db)

    # Only owners can set default
    role = await group_member_service.get_role(group_id, ctx.user.id)
    if role != "owner":
        return RedirectResponse(url="/groups?error=owners_only", status_code=303)

    await group_service.set_default(group_id)

    return RedirectResponse(url="/groups", status_code=303)
