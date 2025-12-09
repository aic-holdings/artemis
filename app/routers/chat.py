"""
Chat page routes for testing Artemis.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import ProviderKey, ProviderAccount
from app.routers.auth_routes import get_current_user, get_user_organizations, get_user_groups
from app.services.api_key_service import APIKeyService
from app.services.provider_model_service import ProviderModelService
from app.auth import decrypt_api_key

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/chat")
async def chat_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    key_id: str = None,
):
    """Chat page for testing Artemis proxy."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    active_org = ctx.active_org

    # Get organizations for dropdown
    organizations = await get_user_organizations(user.id, db)

    # Get groups for current org if in org context
    groups = await get_user_groups(user.id, ctx.active_org_id, db) if ctx.active_org_id else []

    # Track if we're in "All Groups" mode
    all_groups_mode = ctx.active_org_id and not ctx.active_group_id

    # Get available API keys based on group context
    api_key_service = APIKeyService(db)
    api_keys = []
    keys_by_group = {}  # {group_name: [keys]}

    if ctx.active_group_id:
        # When a specific group is selected, show keys from that group
        group_keys = await api_key_service.get_all_for_group(ctx.active_group_id)
        group_keys = [k for k in group_keys if k.revoked_at is None]
        if group_keys:
            keys_by_group[ctx.active_group.name] = group_keys
            api_keys = group_keys
    elif all_groups_mode:
        # "All Groups" mode - show keys from all groups user belongs to
        for group in groups:
            group_keys = await api_key_service.get_all_for_group(group.id)
            group_keys = [k for k in group_keys if k.revoked_at is None]
            if group_keys:
                keys_by_group[group.name] = group_keys
                api_keys.extend(group_keys)
    else:
        # Personal keys (no org/group context)
        personal_keys = await api_key_service.get_all_for_user(user.id, group_id=None)
        personal_keys = [k for k in personal_keys if k.revoked_at is None]
        if personal_keys:
            keys_by_group["Personal"] = personal_keys
            api_keys = personal_keys

    # Determine selected key and reveal it
    selected_key = None
    api_key_value = None

    if key_id:
        # Verify key belongs to user and is in our allowed list
        selected_key = await api_key_service.get_by_id(key_id, user_id=user.id)
        if selected_key and selected_key not in api_keys:
            selected_key = None
        if selected_key and selected_key.encrypted_key:
            api_key_value = await api_key_service.reveal(key_id, user.id)
    elif api_keys:
        # Auto-select first available key
        selected_key = api_keys[0]
        if selected_key.encrypted_key:
            api_key_value = await api_key_service.reveal(selected_key.id, user.id)

    # Get available providers based on user's provider keys
    # ProviderKey -> ProviderAccount (has group_id and provider_id)
    available_providers = []
    if ctx.active_group_id:
        provider_keys_result = await db.execute(
            select(ProviderAccount.provider_id)
            .join(ProviderKey, ProviderKey.provider_account_id == ProviderAccount.id)
            .where(ProviderAccount.group_id == ctx.active_group_id)
            .distinct()
        )
        available_providers = [row[0] for row in provider_keys_result]
    elif all_groups_mode:
        # "All Groups" mode - get providers from all groups user belongs to
        group_ids = [g.id for g in groups]
        if group_ids:
            provider_keys_result = await db.execute(
                select(ProviderAccount.provider_id)
                .join(ProviderKey, ProviderKey.provider_account_id == ProviderAccount.id)
                .where(ProviderAccount.group_id.in_(group_ids))
                .distinct()
            )
            available_providers = [row[0] for row in provider_keys_result]

    # Get enabled models from the database for these providers
    provider_model_service = ProviderModelService(db)
    enabled_models = await provider_model_service.get_enabled_models(
        provider_ids=available_providers if available_providers else None
    )

    # Group models by provider for the template
    # Format: {provider_id: {"name": display_name, "models": [(model_id, name), ...]}}
    available_models = {}
    # Build model metadata for JavaScript (vision capability, etc.)
    model_metadata = {}
    provider_names = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "google": "Google",
        "perplexity": "Perplexity",
        "openrouter": "OpenRouter",
    }

    for model in enabled_models:
        provider_id = model.provider_id
        if provider_id not in available_models:
            available_models[provider_id] = {
                "name": provider_names.get(provider_id, provider_id.title()),
                "models": []
            }
        available_models[provider_id]["models"].append((model.model_id, model.name))

        # Extract vision capability from raw_data
        supports_vision = False
        if model.raw_data:
            input_modalities = model.raw_data.get("architecture", {}).get("input_modalities", [])
            supports_vision = "image" in input_modalities
        model_metadata[model.model_id] = {
            "name": model.name,
            "provider_id": provider_id,
            "supports_vision": supports_vision,
        }

    # Get first available model for default selection
    first_model = None
    if available_models:
        first_provider_data = next(iter(available_models.values()))
        if first_provider_data["models"]:
            first_model = first_provider_data["models"][0][0]  # model_id

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "user": user,
            "active_org": active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "api_keys": api_keys,
            "keys_by_group": keys_by_group,
            "selected_key": selected_key,
            "api_key_value": api_key_value,
            "available_models": available_models,
            "available_providers": available_providers,
            "first_model": first_model,
            "model_metadata": model_metadata,
            "all_groups_mode": all_groups_mode,
        },
    )
