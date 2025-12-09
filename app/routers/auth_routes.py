from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Organization, OrganizationMember, Group, GroupMember
from app.auth import hash_password, verify_password, create_access_token, decode_access_token
from app.config import settings

router = APIRouter()


@dataclass
class UserContext:
    """User context including active organization and default group."""
    user: User
    active_org_id: Optional[str] = None
    active_org: Optional[Organization] = None
    active_group_id: Optional[str] = None
    active_group: Optional[Group] = None

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def email(self) -> str:
        return self.user.email


async def get_or_create_localhost_user(db: AsyncSession) -> User:
    """Get or create the localhost auto-login user."""
    result = await db.execute(
        select(User).where(User.email == settings.LOCALHOST_USER_EMAIL)
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            email=settings.LOCALHOST_USER_EMAIL,
            password_hash=hash_password("localhost-auto-login"),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user


def is_localhost_request(request: Request) -> bool:
    """Check if request is from localhost."""
    host = request.headers.get("host", "")
    # Check common localhost patterns
    return host.startswith("localhost") or host.startswith("127.0.0.1") or host.startswith("0.0.0.0")


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> UserContext | None:
    """Get current user context from session cookie, or auto-login in localhost mode."""
    user = None
    active_org_id = None

    # Localhost mode - auto-login when running locally
    if settings.LOCALHOST_MODE and is_localhost_request(request):
        user = await get_or_create_localhost_user(db)
        # For localhost, check for org in cookie (simpler than JWT for dev)
        active_org_id = request.cookies.get("active_org")
    else:
        token = request.cookies.get("session")
        if not token:
            return None

        payload = decode_access_token(token)
        if not payload:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        active_org_id = payload.get("org")

    if not user:
        return None

    # If no org selected via cookie/JWT, check user settings for last selected org
    if not active_org_id:
        active_org_id = user.get_setting("last_org_id")

    # Load active org if set
    active_org = None
    active_group = None
    active_group_id = None

    if active_org_id:
        result = await db.execute(select(Organization).where(Organization.id == active_org_id))
        active_org = result.scalar_one_or_none()

        # Load group - only if explicitly selected (allow "All Groups" mode)
        if active_org:
            # Check for explicitly selected group (from user settings)
            saved_group_id = user.get_setting("last_group_id")
            if saved_group_id:
                # Verify user is still a member of this group and it belongs to this org
                result = await db.execute(
                    select(Group)
                    .join(GroupMember, GroupMember.group_id == Group.id)
                    .where(
                        Group.id == saved_group_id,
                        Group.organization_id == active_org_id,
                        GroupMember.user_id == user.id
                    )
                )
                active_group = result.scalar_one_or_none()
                if active_group:
                    active_group_id = active_group.id
            # If no saved group or saved group is invalid, stay in "All Groups" mode
            # (active_group_id remains None)

    return UserContext(
        user=user,
        active_org_id=active_org_id,
        active_org=active_org,
        active_group_id=active_group_id,
        active_group=active_group
    )


async def require_user(request: Request, db: AsyncSession = Depends(get_db)) -> UserContext:
    """Require authenticated user, redirect to login if not."""
    ctx = await get_current_user(request, db)
    if not ctx:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return ctx


async def get_user_organizations(user_id: str, db: AsyncSession) -> list[Organization]:
    """Get all organizations a user has access to (owned or member of)."""
    # Get orgs user owns
    owned_result = await db.execute(
        select(Organization).where(Organization.owner_id == user_id)
    )
    owned_orgs = list(owned_result.scalars().all())
    org_ids = {o.id for o in owned_orgs}

    # Get orgs user is a member of (active membership)
    member_result = await db.execute(
        select(Organization)
        .join(OrganizationMember)
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active"
        )
    )
    member_orgs = list(member_result.scalars().all())

    # Combine unique orgs
    for org in member_orgs:
        if org.id not in org_ids:
            owned_orgs.append(org)
            org_ids.add(org.id)

    return owned_orgs


async def get_user_groups(user_id: str, org_id: str, db: AsyncSession) -> list[Group]:
    """Get all groups a user is a member of within an organization."""
    result = await db.execute(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(
            Group.organization_id == org_id,
            GroupMember.user_id == user_id
        )
        .order_by(Group.is_default.desc(), Group.name)  # Default group first
    )
    return list(result.scalars().all())


async def get_user_group_role(user_id: str, group_id: str, db: AsyncSession) -> Optional[str]:
    """Get user's role in a specific group (owner, admin, member) or None if not a member."""
    result = await db.execute(
        select(GroupMember.role)
        .where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    return row


@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Register a new user."""
    # Check if user exists
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        # Return to register page with error (we'll handle this in template)
        return RedirectResponse(url="/register?error=exists", status_code=303)

    # Create user
    user = User(
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    await db.commit()

    # Create session token
    token = create_access_token({"sub": user.id})
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        max_age=settings.JWT_EXPIRATION_HOURS * 3600,
        samesite="lax",
    )
    return response


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Login user."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse(url="/login?error=invalid", status_code=303)

    # Create session token
    token = create_access_token({"sub": user.id})
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        max_age=settings.JWT_EXPIRATION_HOURS * 3600,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    """Logout user."""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session")
    response.delete_cookie("active_org")
    return response


@router.post("/switch-org")
async def switch_org(
    request: Request,
    org_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Switch active organization."""
    ctx = await get_current_user(request, db)
    if not ctx:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    # Verify org exists
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Save last selected org to user settings for persistence across sessions
    # Clear the group selection since it's org-specific
    ctx.user.set_setting("last_org_id", org_id)
    ctx.user.set_setting("last_group_id", None)
    await db.commit()

    # Set org in cookie (simple approach for localhost mode)
    response = RedirectResponse(url="/settings", status_code=303)
    response.set_cookie(
        key="active_org",
        value=org_id,
        httponly=True,
        max_age=settings.JWT_EXPIRATION_HOURS * 3600,
        samesite="lax",
    )
    return response


@router.post("/clear-org")
async def clear_org(request: Request, db: AsyncSession = Depends(get_db)):
    """Clear active organization (show all personal data)."""
    ctx = await get_current_user(request, db)
    if ctx:
        # Clear the saved org and group from user settings
        ctx.user.set_setting("last_org_id", None)
        ctx.user.set_setting("last_group_id", None)
        await db.commit()

    response = RedirectResponse(url="/settings", status_code=303)
    response.delete_cookie("active_org")
    return response


@router.post("/switch-group")
async def switch_group(
    request: Request,
    group_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Switch active group within the current organization."""
    ctx = await get_current_user(request, db)
    if not ctx:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    if not ctx.active_org_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    # Verify group exists, belongs to current org, and user is a member
    result = await db.execute(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(
            Group.id == group_id,
            Group.organization_id == ctx.active_org_id,
            GroupMember.user_id == ctx.user.id
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found or access denied")

    # Save selected group to user settings
    ctx.user.set_setting("last_group_id", group_id)
    await db.commit()

    # Get referer to redirect back to current page
    referer = request.headers.get("referer", "/settings")
    response = RedirectResponse(url=referer, status_code=303)
    return response


@router.post("/clear-group")
async def clear_group(request: Request, db: AsyncSession = Depends(get_db)):
    """Clear active group selection (view all groups in current org)."""
    ctx = await get_current_user(request, db)
    if ctx:
        # Clear the saved group from user settings
        ctx.user.set_setting("last_group_id", None)
        await db.commit()

    # Get referer to redirect back to current page
    referer = request.headers.get("referer", "/settings")
    response = RedirectResponse(url=referer, status_code=303)
    return response
