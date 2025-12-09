"""
Provider API key management routes.

Hierarchy: Provider → ProviderAccount → ProviderKey
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.auth_routes import get_current_user, get_user_organizations, get_user_groups
from app.services.provider_service import ProviderService
from app.services.provider_account_service import ProviderAccountService
from app.services.provider_key_service import ProviderKeyService
from app.services.provider_model_service import ProviderModelService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/providers")
async def providers_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Provider API key management page."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)

    # Get groups for current org if in org context
    groups = []
    if ctx.active_org_id:
        groups = await get_user_groups(user.id, ctx.active_org_id, db)

    # Get all providers (reference data)
    provider_service = ProviderService(db)
    providers = await provider_service.get_all(active_only=True)

    # Get accounts and keys for the current group
    provider_account_service = ProviderAccountService(db)
    provider_key_service = ProviderKeyService(db)

    # Track whether we're in "All Groups" mode (org selected but no specific group)
    all_groups_mode = ctx.active_org_id and not ctx.active_group_id

    # Organize data by provider: {provider_id: {provider, accounts: [{account, keys}]}}
    provider_data = {}

    if ctx.active_group_id:
        # Specific group selected
        accounts = await provider_account_service.get_all_for_group(
            ctx.active_group_id, include_keys=True
        )

        for account in accounts:
            if account.provider_id not in provider_data:
                provider_data[account.provider_id] = {
                    "accounts": [],
                }
            provider_data[account.provider_id]["accounts"].append({
                "account": account,
                "keys": list(account.keys),
            })
    elif ctx.active_org_id:
        # "All Groups" mode - show accounts/keys from all groups user is member of
        for group in groups:
            accounts = await provider_account_service.get_all_for_group(
                group.id, include_keys=True
            )

            for account in accounts:
                if account.provider_id not in provider_data:
                    provider_data[account.provider_id] = {
                        "accounts": [],
                    }
                provider_data[account.provider_id]["accounts"].append({
                    "account": account,
                    "keys": list(account.keys),
                    "group_name": group.name,  # Track which group this account belongs to
                })

    # Get model counts per provider
    provider_model_service = ProviderModelService(db)
    model_counts = await provider_model_service.get_model_count_by_provider()

    return templates.TemplateResponse(
        request,
        "providers.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "providers": providers,
            "provider_data": provider_data,
            "model_counts": model_counts,
            "all_groups_mode": all_groups_mode,
        },
    )


@router.post("/providers/{provider_id}/accounts")
async def create_provider_account(
    provider_id: str,
    request: Request,
    name: str = Form(...),
    account_email: str = Form(""),
    account_phone: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Create a new provider account."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    if not ctx.active_group_id:
        return RedirectResponse(url="/providers?error=no_group", status_code=303)

    provider_account_service = ProviderAccountService(db)

    # Check for duplicate name
    if await provider_account_service.name_exists(
        ctx.active_group_id, provider_id, name.strip() or "Default"
    ):
        return RedirectResponse(url="/providers?error=duplicate_account_name", status_code=303)

    await provider_account_service.create(
        group_id=ctx.active_group_id,
        provider_id=provider_id,
        name=name.strip() or "Default",
        created_by_id=ctx.user.id,
        account_email=account_email.strip() or None,
        account_phone=account_phone.strip() or None,
    )

    return RedirectResponse(url="/providers", status_code=303)


@router.post("/providers/accounts/{account_id}/keys")
async def create_provider_key(
    account_id: str,
    request: Request,
    api_key: str = Form(...),
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Create a new provider key for an account."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    provider_key_service = ProviderKeyService(db)

    # Check for duplicate name
    if await provider_key_service.name_exists(account_id, name.strip() or "Default"):
        return RedirectResponse(url="/providers?error=duplicate_key_name", status_code=303)

    await provider_key_service.create(
        provider_account_id=account_id,
        user_id=ctx.user.id,
        key=api_key,
        name=name.strip() or "Default",
    )

    return RedirectResponse(url="/providers", status_code=303)


@router.post("/providers/{provider_id}")
async def save_provider_key_simple(
    provider_id: str,
    request: Request,
    api_key: str = Form(...),
    name: str = Form(...),
    account_email: str = Form(""),
    account_phone: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """
    Simple endpoint to add a provider key.

    This creates or uses a default account for the provider and adds the key to it.
    Provides backwards compatibility with the simpler UX.
    """
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    if not ctx.active_group_id:
        return RedirectResponse(url="/providers?error=no_group", status_code=303)

    provider_account_service = ProviderAccountService(db)
    provider_key_service = ProviderKeyService(db)

    # Get or create a default account for this provider
    account = await provider_account_service.get_or_create_default(
        group_id=ctx.active_group_id,
        provider_id=provider_id,
        created_by_id=ctx.user.id,
    )

    # Update account contact info if provided
    if account_email or account_phone:
        await provider_account_service.update(
            account_id=account.id,
            account_email=account_email.strip() or None,
            account_phone=account_phone.strip() or None,
        )

    # Check for duplicate key name
    if await provider_key_service.name_exists(account.id, name.strip() or "Default"):
        return RedirectResponse(url="/providers?error=duplicate_key_name", status_code=303)

    # Create the key
    await provider_key_service.create(
        provider_account_id=account.id,
        user_id=ctx.user.id,
        key=api_key,
        name=name.strip() or "Default",
    )

    return RedirectResponse(url="/providers", status_code=303)


@router.post("/providers/key/{key_id}/delete")
async def delete_provider_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a provider API key."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    provider_key_service = ProviderKeyService(db)
    await provider_key_service.delete(key_id, ctx.user.id)

    return RedirectResponse(url="/providers", status_code=303)


@router.post("/providers/key/{key_id}/set-default")
async def set_default_provider_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Set a provider key as the default for its provider."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    provider_key_service = ProviderKeyService(db)
    await provider_key_service.set_default(key_id, ctx.user.id)

    return RedirectResponse(url="/providers", status_code=303)


@router.get("/providers/key/{key_id}/reveal")
async def reveal_provider_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Reveal a provider API key (returns JSON)."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    provider_key_service = ProviderKeyService(db)
    decrypted = await provider_key_service.decrypt_key(key_id, ctx.user.id)

    if not decrypted:
        return JSONResponse({"error": "Key not found"}, status_code=404)

    return JSONResponse({"key": decrypted})


@router.post("/providers/accounts/{account_id}/delete")
async def delete_provider_account(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a provider account and all its keys."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    provider_account_service = ProviderAccountService(db)
    await provider_account_service.delete(account_id)

    return RedirectResponse(url="/providers", status_code=303)


# ============================================================================
# Provider Model Management
# ============================================================================


@router.post("/providers/{provider_id}/models/sync")
async def sync_provider_models(
    provider_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Sync models from provider API.

    Currently supports OpenRouter - fetches available models and updates local database.
    """
    ctx = await get_current_user(request, db)
    if not ctx:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if provider_id != "openrouter":
        return JSONResponse(
            {"error": "Model sync only supported for OpenRouter currently"},
            status_code=400,
        )

    # Get an OpenRouter API key from this group to use for the sync
    provider_key_service = ProviderKeyService(db)
    api_key = None

    if ctx.active_group_id:
        key = await provider_key_service.get_default_for_provider(
            ctx.active_group_id, "openrouter"
        )
        if key:
            api_key = await provider_key_service.decrypt_key(key.id, ctx.user.id)

    provider_model_service = ProviderModelService(db)

    try:
        result = await provider_model_service.sync_openrouter_models(api_key)
        return JSONResponse({
            "success": True,
            "added": result["added"],
            "updated": result["updated"],
            "total": result["total"],
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/providers/models/{model_id}/toggle")
async def toggle_provider_model(
    model_id: str,
    request: Request,
    enabled: bool = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Toggle a model's enabled state."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    provider_model_service = ProviderModelService(db)
    model = await provider_model_service.toggle_model(model_id, enabled)

    if not model:
        return JSONResponse({"error": "Model not found"}, status_code=404)

    return JSONResponse({
        "success": True,
        "model_id": model.model_id,
        "enabled": model.is_enabled,
    })


@router.get("/providers/{provider_id}/models")
async def get_provider_models(
    provider_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get all models for a provider."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    provider_model_service = ProviderModelService(db)
    models = await provider_model_service.get_all_for_provider(provider_id)

    return JSONResponse({
        "models": [
            {
                "id": m.id,
                "model_id": m.model_id,
                "name": m.name,
                "description": m.description,
                "context_length": m.context_length,
                "max_completion_tokens": m.max_completion_tokens,
                "input_price_per_1m": m.input_price_per_1m,
                "output_price_per_1m": m.output_price_per_1m,
                "is_enabled": m.is_enabled,
                "last_synced_at": m.last_synced_at.isoformat() if m.last_synced_at else None,
                "raw_data": m.raw_data,
            }
            for m in models
        ]
    })
