"""
API key management routes.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.auth_routes import get_current_user, get_user_organizations, get_user_groups
from app.services.api_key_service import APIKeyService
from app.services.provider_key_service import ProviderKeyService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PROVIDERS = ["openai", "anthropic", "google", "perplexity", "openrouter"]


@router.get("/api-keys")
async def api_keys_page(request: Request, db: AsyncSession = Depends(get_db)):
    """API key management page."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)

    # Get groups for current org if in org context
    groups = []
    if ctx.active_org_id:
        groups = await get_user_groups(user.id, ctx.active_org_id, db)

    # Use services to get API keys and provider keys based on group context
    api_key_service = APIKeyService(db)
    provider_key_service = ProviderKeyService(db)

    # Track whether we're in "All Groups" mode (org selected but no specific group)
    all_groups_mode = ctx.active_org_id and not ctx.active_group_id

    # Get API keys - filtered by group if in group context
    api_keys = []
    all_provider_keys = []
    if ctx.active_group_id:
        # Specific group selected
        api_keys = await api_key_service.get_all_for_group(ctx.active_group_id)
        all_provider_keys = await provider_key_service.get_all_for_group(
            ctx.active_group_id, include_account=True
        )
    elif ctx.active_org_id:
        # "All Groups" mode - show keys from all groups user is member of
        for group in groups:
            group_keys = await api_key_service.get_all_for_group(group.id)
            api_keys.extend(group_keys)
            group_provider_keys = await provider_key_service.get_all_for_group(
                group.id, include_account=True
            )
            all_provider_keys.extend(group_provider_keys)
    else:
        # Personal keys (no org/group)
        api_keys = await api_key_service.get_all_for_user(user.id, group_id=None)
        all_provider_keys = await provider_key_service.get_all_for_user(user.id, group_id=None)

    provider_keys_by_provider = {}
    for pk in all_provider_keys:
        # ProviderKey -> ProviderAccount -> provider_id
        provider_id = pk.account.provider_id if pk.account else None
        if provider_id:
            if provider_id not in provider_keys_by_provider:
                provider_keys_by_provider[provider_id] = []
            provider_keys_by_provider[provider_id].append(pk)

    return templates.TemplateResponse(
        request,
        "api_keys.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "api_keys": api_keys,
            "provider_keys": provider_keys_by_provider,
            "providers": PROVIDERS,
            "all_groups_mode": all_groups_mode,
        },
    )


@router.post("/api-keys")
async def create_api_key(
    request: Request,
    name: str = Form("Default"),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user

    # Cannot create keys in "All Groups" mode - must select a specific group
    if ctx.active_org_id and not ctx.active_group_id:
        return RedirectResponse(
            url="/api-keys?error=select_group",
            status_code=303
        )

    api_key_service = APIKeyService(db)

    # Normalize empty name to "Default"
    original_name = name.strip()
    name = original_name or "Default"

    # Check for duplicate name (group-scoped)
    if await api_key_service.name_exists(user.id, name, ctx.active_group_id):
        # Name already exists - show error with helpful message
        if not original_name:
            error_msg = "A 'Default' key already exists. Please enter a unique name for your new key."
        else:
            error_msg = f"A key named '{name}' already exists. Please choose a different name."

        if ctx.active_group_id:
            api_keys = await api_key_service.get_all_for_group(ctx.active_group_id)
        else:
            api_keys = await api_key_service.get_all_for_user(user.id, group_id=None)

        organizations = await get_user_organizations(user.id, db)
        groups = []
        if ctx.active_org_id:
            groups = await get_user_groups(user.id, ctx.active_org_id, db)

        return templates.TemplateResponse(
            request,
            "api_keys.html",
            {
                "user": user,
                "active_org": ctx.active_org,
                "active_group": ctx.active_group,
                "organizations": organizations,
                "groups": groups,
                "api_keys": api_keys,
                "error": error_msg,
                "providers": PROVIDERS,
                "provider_keys": {},
            },
        )

    # Create the key with group_id
    api_key, full_key = await api_key_service.create(
        user_id=user.id,
        name=name,
        group_id=ctx.active_group_id
    )

    # Return page with the new key shown (only time it's visible)
    if ctx.active_group_id:
        api_keys = await api_key_service.get_all_for_group(ctx.active_group_id)
    else:
        api_keys = await api_key_service.get_all_for_user(user.id, group_id=None)

    organizations = await get_user_organizations(user.id, db)
    groups = []
    if ctx.active_org_id:
        groups = await get_user_groups(user.id, ctx.active_org_id, db)

    return templates.TemplateResponse(
        request,
        "api_keys.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "api_keys": api_keys,
            "new_key": full_key,
            "providers": PROVIDERS,
            "provider_keys": {},
        },
    )


@router.post("/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API key."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    api_key_service = APIKeyService(db)

    # Verify key belongs to user and optionally to the active group
    api_key = await api_key_service.get_by_id(
        key_id, user_id=ctx.user.id, group_id=ctx.active_group_id
    )

    # Prevent revoking system keys
    if api_key and not api_key.is_system:
        api_key.revoked_at = datetime.now(timezone.utc)
        await db.commit()

    return RedirectResponse(url="/api-keys", status_code=303)


@router.get("/api-keys/{key_id}/reveal")
async def reveal_api_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Reveal an API key (returns JSON)."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    api_key_service = APIKeyService(db)

    # For reveal, we allow access if user owns the key (regardless of current group context)
    # This is because the reveal modal can be triggered from any context
    api_key = await api_key_service.get_by_id(key_id, user_id=ctx.user.id)

    if not api_key:
        return JSONResponse({"error": "Key not found"}, status_code=404)

    if not api_key.encrypted_key:
        return JSONResponse({"error": "Key cannot be revealed (created before this feature)"}, status_code=400)

    decrypted = await api_key_service.reveal(key_id, ctx.user.id)
    return JSONResponse({"key": decrypted})


@router.post("/api-keys/{key_id}/overrides")
async def update_api_key_overrides(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update provider key overrides for an API key."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    api_key_service = APIKeyService(db)
    provider_key_service = ProviderKeyService(db)

    # Verify key belongs to user
    api_key = await api_key_service.get_by_id(key_id, user_id=ctx.user.id)

    # Cannot modify system keys
    if not api_key or api_key.is_system:
        return RedirectResponse(url="/api-keys", status_code=303)

    # Parse form data for provider overrides
    form_data = await request.form()
    overrides = {}
    for provider in PROVIDERS:
        provider_key_id = form_data.get(f"provider_{provider}")
        if provider_key_id and provider_key_id != "default":
            # Verify the provider key belongs to this user (in same group scope)
            pk = await provider_key_service.get_by_id(
                provider_key_id, user_id=ctx.user.id, group_id=api_key.group_id
            )
            if pk:
                overrides[provider] = provider_key_id

    api_key.provider_key_overrides = overrides if overrides else None
    await db.commit()

    return RedirectResponse(url="/api-keys", status_code=303)
