from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Organization, OrganizationMember, Group, GroupMember
from app.auth import hash_password, verify_password, create_access_token, decode_access_token
from app.config import settings
from app.jetta_sso import get_sso_client

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


async def get_or_create_sso_user(sso_user: dict, db: AsyncSession) -> User:
    """
    Get or create a local Artemis user from Jetta SSO user info.

    Uses supabase_id (stable) as primary lookup, with email as fallback for migration.

    Args:
        sso_user: User dict from Jetta SSO containing id, email, display_name, etc.
        db: Database session

    Returns:
        Local Artemis User object
    """
    supabase_id = sso_user.get("id")  # Stable Supabase UUID
    email = sso_user.get("email")

    if not email:
        raise ValueError("SSO user missing email")

    user = None

    # Primary lookup: by supabase_id (stable identifier)
    if supabase_id:
        result = await db.execute(select(User).where(User.supabase_id == supabase_id))
        user = result.scalar_one_or_none()

    # Fallback: by email (for users created before supabase_id was added)
    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        # Migration: if found by email but missing supabase_id, add it
        if user and supabase_id and not user.supabase_id:
            user.supabase_id = supabase_id
            await db.commit()
            print(f"Migrated user {email}: added supabase_id {supabase_id}")

    if not user:
        # Create new user from SSO data
        import secrets
        user = User(
            supabase_id=supabase_id,
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"Created new Artemis user from SSO: {email} (supabase_id: {supabase_id})")
    elif user.email != email:
        # User found by supabase_id but email changed - update it
        old_email = user.email
        user.email = email
        await db.commit()
        print(f"Updated user email: {old_email} -> {email} (supabase_id: {supabase_id})")

    return user


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> UserContext | None:
    """Get current user context from session cookie, SSO cookie, or auto-login in localhost mode."""
    user = None
    active_org_id = None

    # Localhost mode - auto-login when running locally
    if settings.LOCALHOST_MODE and is_localhost_request(request):
        user = await get_or_create_localhost_user(db)
        # For localhost, check for org in cookie (simpler than JWT for dev)
        active_org_id = request.cookies.get("active_org")
    else:
        # Try local session token first
        token = request.cookies.get("session")
        if token:
            payload = decode_access_token(token)
            if payload:
                user_id = payload.get("sub")
                if user_id:
                    result = await db.execute(select(User).where(User.id == user_id))
                    user = result.scalar_one_or_none()
                    active_org_id = payload.get("org")

        # If no local session, try Jetta SSO (if enabled)
        if not user and settings.SSO_ENABLED:
            sso_client = get_sso_client()
            sso_user = await sso_client.get_current_user(request)
            if sso_user:
                # Get or create local user from SSO user info
                user = await get_or_create_sso_user(sso_user, db)
                # For SSO users, check for org in cookie
                active_org_id = request.cookies.get("active_org")

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


@router.get("/logout")
async def logout():
    """Logout user - clears local session and optionally SSO session."""
    # Clear local session cookies
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session")
    response.delete_cookie("active_org")

    # If SSO is enabled, redirect to SSO logout to clear the SSO cookie too
    if settings.SSO_ENABLED:
        sso_client = get_sso_client()
        # Redirect to SSO logout, which will then redirect back to Artemis home
        return RedirectResponse(
            url=sso_client.logout_url(redirect_uri=f"{settings.ARTEMIS_URL}/"),
            status_code=303
        )

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


# =============================================================================
# Jetta SSO Routes
# =============================================================================

@router.get("/sso/callback")
async def sso_callback(request: Request, redirect_uri: str = "/dashboard"):
    """
    SSO callback endpoint - handles return from Jetta SSO login.

    Simply redirects to the requested page since the jetta_token cookie
    is already set by Jetta SSO on .jettaintelligence.com domain.
    """
    return RedirectResponse(url=redirect_uri, status_code=303)


@router.get("/sso/logout")
async def sso_logout(request: Request, redirect_uri: str = "/"):
    """
    Logout from both Artemis and Jetta SSO.

    Clears local session cookie and redirects to SSO logout.
    """
    # Clear local session
    response = RedirectResponse(url=redirect_uri, status_code=303)
    response.delete_cookie("session")
    response.delete_cookie("active_org")

    # If SSO enabled, also clear via Jetta SSO
    # Note: The jetta_token cookie is on .jettaintelligence.com domain,
    # so Artemis can't directly clear it. User needs to visit Jetta SSO logout.
    if settings.SSO_ENABLED:
        sso_client = get_sso_client()
        # Redirect to SSO logout which will clear the SSO cookie
        return RedirectResponse(
            url=sso_client.logout_url(redirect_uri=f"{settings.ARTEMIS_URL}{redirect_uri}"),
            status_code=303
        )

    return response


@router.get("/sso/status")
async def sso_status(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Check SSO authentication status.

    Returns JSON with current auth status - useful for JavaScript polling.
    """
    ctx = await get_current_user(request, db)

    if ctx:
        return {
            "authenticated": True,
            "email": ctx.email,
            "sso_enabled": settings.SSO_ENABLED,
        }

    return {
        "authenticated": False,
        "sso_enabled": settings.SSO_ENABLED,
        "login_url": f"/sso/login" if settings.SSO_ENABLED else "/login",
    }


@router.get("/admin/list-users")
async def admin_list_users(
    secret: str,
    db: AsyncSession = Depends(get_db),
):
    """List all users - temporary admin endpoint."""
    if secret != "artemis-merge-2024-dshanklin":
        raise HTTPException(status_code=403, detail="Invalid secret")

    result = await db.execute(select(User))
    users = result.scalars().all()

    return {
        "users": [
            {"id": u.id, "email": u.email, "created_at": str(u.created_at)}
            for u in users
        ]
    }


@router.post("/admin/merge-user")
async def admin_merge_user(
    request: Request,
    old_email: str = Form(...),
    new_email: str = Form(...),
    secret: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    One-time admin endpoint to merge user accounts.
    Transfers all data from old_email user to new_email user.
    Protected by a secret token.
    """
    # Simple secret protection - this is a one-time migration
    if secret != "artemis-merge-2024-dshanklin":
        raise HTTPException(status_code=403, detail="Invalid secret")

    # Find both users
    old_result = await db.execute(select(User).where(User.email == old_email))
    old_user = old_result.scalar_one_or_none()

    new_result = await db.execute(select(User).where(User.email == new_email))
    new_user = new_result.scalar_one_or_none()

    if not old_user:
        return {"error": f"Old user {old_email} not found"}
    if not new_user:
        return {"error": f"New user {new_email} not found"}

    old_id = old_user.id
    new_id = new_user.id
    changes = []

    # Transfer organization ownership
    from app.models import Organization, OrganizationMember, Group, GroupMember, APIKey, ProviderKey

    # Organizations owned by old user
    orgs = await db.execute(select(Organization).where(Organization.owner_id == old_id))
    for org in orgs.scalars().all():
        org.owner_id = new_id
        changes.append(f"Transferred org ownership: {org.name}")

    # Organization memberships
    memberships = await db.execute(select(OrganizationMember).where(OrganizationMember.user_id == old_id))
    for mem in memberships.scalars().all():
        mem.user_id = new_id
        mem.email = new_email
        changes.append(f"Transferred org membership: {mem.organization_id}")

    # Group memberships
    group_mems = await db.execute(select(GroupMember).where(GroupMember.user_id == old_id))
    for gm in group_mems.scalars().all():
        gm.user_id = new_id
        changes.append(f"Transferred group membership: {gm.group_id}")

    # Groups created by old user
    groups = await db.execute(select(Group).where(Group.created_by_id == old_id))
    for g in groups.scalars().all():
        g.created_by_id = new_id
        changes.append(f"Transferred group creator: {g.name}")

    # API Keys
    api_keys = await db.execute(select(APIKey).where(APIKey.user_id == old_id))
    for key in api_keys.scalars().all():
        key.user_id = new_id
        changes.append(f"Transferred API key: {key.name}")

    # Provider Keys
    provider_keys = await db.execute(select(ProviderKey).where(ProviderKey.user_id == old_id))
    for pk in provider_keys.scalars().all():
        pk.user_id = new_id
        changes.append(f"Transferred provider key: {pk.name}")

    # Transfer settings from old user to new user
    if old_user.settings:
        new_user.settings = {**(new_user.settings or {}), **old_user.settings}
        changes.append("Transferred user settings")

    # Commit changes
    await db.commit()

    return {
        "success": True,
        "old_user": old_email,
        "new_user": new_email,
        "changes": changes,
    }
