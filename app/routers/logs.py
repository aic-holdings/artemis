"""
Usage logs viewing routes.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models import APIKey, UsageLog, AppLog
from app.routers.auth_routes import get_current_user, get_user_organizations, get_user_groups

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/logs")
async def logs_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    provider: str = None,
    app_id: str = None,
    model: str = None,
    key_id: str = None,
    page: int = 1,
):
    """Usage logs page with filtering and pagination."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)
    per_page = 50

    # Get groups for filter dropdown (if in org context)
    groups = []
    if ctx.active_org_id:
        groups = await get_user_groups(user.id, ctx.active_org_id, db)

    # Track if we're in "All Groups" mode
    all_groups_mode = ctx.active_org_id and not ctx.active_group_id

    # Build API key filter conditions based on group context
    api_key_conditions = [APIKey.user_id == user.id]
    if ctx.active_group_id:
        api_key_conditions.append(APIKey.group_id == ctx.active_group_id)
    elif all_groups_mode:
        # "All Groups" mode - get keys from all groups user belongs to
        group_ids = [g.id for g in groups]
        if group_ids:
            api_key_conditions.append(APIKey.group_id.in_(group_ids))
        else:
            api_key_conditions.append(APIKey.group_id.is_(None))  # Fallback
    else:
        api_key_conditions.append(APIKey.group_id.is_(None))

    # Get user's API keys (including revoked for history) - filtered by group
    all_keys_result = await db.execute(
        select(APIKey).where(*api_key_conditions).order_by(APIKey.created_at.desc())
    )
    all_api_keys = all_keys_result.scalars().all()

    # Get active keys for filtering
    api_keys_result = await db.execute(
        select(APIKey).where(*api_key_conditions, APIKey.revoked_at.is_(None))
    )
    api_keys = api_keys_result.scalars().all()
    api_key_ids = [k.id for k in api_keys]

    # If filtering by specific key, use that instead
    if key_id:
        # Verify key belongs to user and matches group context
        key_check = await db.execute(
            select(APIKey).where(APIKey.id == key_id, *api_key_conditions)
        )
        if key_check.scalar_one_or_none():
            api_key_ids = [key_id]

    logs = []
    total_count = 0
    total_pages = 1
    app_ids = []
    models = []

    if api_key_ids:
        # Build filter conditions
        base_conditions = [UsageLog.api_key_id.in_(api_key_ids)]
        if provider:
            base_conditions.append(UsageLog.provider == provider)
        if app_id:
            base_conditions.append(UsageLog.app_id == app_id)
        if model:
            base_conditions.append(UsageLog.model == model)

        # Get distinct app_ids for filter
        app_ids_result = await db.execute(
            select(UsageLog.app_id)
            .where(UsageLog.api_key_id.in_(api_key_ids))
            .where(UsageLog.app_id.isnot(None))
            .distinct()
        )
        app_ids = [row[0] for row in app_ids_result if row[0]]

        # Get distinct models for filter
        models_result = await db.execute(
            select(UsageLog.model)
            .where(UsageLog.api_key_id.in_(api_key_ids))
            .distinct()
            .order_by(UsageLog.model)
        )
        models = [row[0] for row in models_result if row[0] != "unknown"]

        # Get total count
        count_result = await db.execute(
            select(func.count(UsageLog.id)).where(*base_conditions)
        )
        total_count = count_result.scalar() or 0
        total_pages = max(1, (total_count + per_page - 1) // per_page)

        # Ensure page is within bounds
        page = max(1, min(page, total_pages))

        # Get logs for current page
        logs_result = await db.execute(
            select(UsageLog)
            .where(*base_conditions)
            .order_by(UsageLog.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        logs = logs_result.scalars().all()

    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "logs": logs,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": total_pages,
            "app_ids": app_ids,
            "models": models,
            "api_keys": all_api_keys,
            "filter_provider": provider,
            "filter_app_id": app_id,
            "filter_model": model,
            "filter_key_id": key_id,
        },
    )


@router.get("/app-logs")
async def app_logs_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    source: str = None,
    level: str = None,
    error_type: str = None,
    page: int = 1,
):
    """Application logs page for viewing frontend/backend error logs."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)
    per_page = 50

    # Build filter conditions
    conditions = []
    if source:
        conditions.append(AppLog.source == source)
    if level:
        conditions.append(AppLog.level == level)
    if error_type:
        conditions.append(AppLog.error_type == error_type)

    # Get distinct sources for filter
    sources_result = await db.execute(
        select(AppLog.source).distinct().order_by(AppLog.source)
    )
    sources = [row[0] for row in sources_result if row[0]]

    # Get distinct levels for filter
    levels_result = await db.execute(
        select(AppLog.level).distinct().order_by(AppLog.level)
    )
    levels = [row[0] for row in levels_result if row[0]]

    # Get distinct error types for filter
    error_types_result = await db.execute(
        select(AppLog.error_type)
        .where(AppLog.error_type.isnot(None))
        .distinct()
        .order_by(AppLog.error_type)
    )
    error_types = [row[0] for row in error_types_result if row[0]]

    # Get total count
    if conditions:
        count_result = await db.execute(
            select(func.count(AppLog.id)).where(*conditions)
        )
    else:
        count_result = await db.execute(select(func.count(AppLog.id)))
    total_count = count_result.scalar() or 0
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    # Ensure page is within bounds
    page = max(1, min(page, total_pages))

    # Get logs for current page
    query = select(AppLog).order_by(AppLog.created_at.desc())
    if conditions:
        query = query.where(*conditions)
    query = query.offset((page - 1) * per_page).limit(per_page)

    logs_result = await db.execute(query)
    logs = logs_result.scalars().all()

    return templates.TemplateResponse(
        request,
        "app_logs.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "logs": logs,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": total_pages,
            "sources": sources,
            "levels": levels,
            "error_types": error_types,
            "filter_source": source,
            "filter_level": level,
            "filter_error_type": error_type,
        },
    )
