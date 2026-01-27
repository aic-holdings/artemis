"""
Service management routes.
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Service, Team, APIKey, UsageLog, Group, utc_now
from app.routers.auth_routes import get_current_user, get_user_organizations, get_user_groups
from app.auth import generate_api_key

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/services")
async def services_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Services management page - lists services in current organization."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)
    groups = await get_user_groups(user.id, ctx.active_org_id, db) if ctx.active_org_id else []

    # Check if user is platform admin
    is_platform_admin = getattr(user, 'is_platform_admin', False)

    # Services are only relevant when viewing an organization (or platform admin)
    if not ctx.active_org_id and not is_platform_admin:
        return templates.TemplateResponse(
            request,
            "services.html",
            {
                "user": user,
                "active_org": None,
                "active_group": ctx.active_group,
                "organizations": organizations,
                "groups": groups,
                "services": [],
                "teams": [],
                "is_platform_admin": is_platform_admin,
                "error": "Select an organization to manage services.",
            },
        )

    # Get services for this org
    if is_platform_admin and not ctx.active_org_id:
        # Platform admin with no org selected - show all services
        services_result = await db.execute(
            select(Service)
            .where(Service.deleted_at.is_(None))
            .options(selectinload(Service.team))
            .order_by(Service.name)
        )
    else:
        services_result = await db.execute(
            select(Service)
            .where(
                Service.organization_id == ctx.active_org_id,
                Service.deleted_at.is_(None)
            )
            .options(selectinload(Service.team))
            .order_by(Service.name)
        )
    services = list(services_result.scalars().all())

    # Get teams for dropdown
    if is_platform_admin and not ctx.active_org_id:
        teams_result = await db.execute(
            select(Team).where(Team.deleted_at.is_(None)).order_by(Team.name)
        )
    else:
        teams_result = await db.execute(
            select(Team)
            .where(
                Team.organization_id == ctx.active_org_id,
                Team.deleted_at.is_(None)
            )
            .order_by(Team.name)
        )
    teams = list(teams_result.scalars().all())

    # Get stats for each service
    services_with_info = []
    for service in services:
        # Count API keys linked to this service
        key_count_result = await db.execute(
            select(func.count(APIKey.id))
            .where(APIKey.service_id == service.id, APIKey.revoked_at.is_(None))
        )
        key_count = key_count_result.scalar() or 0

        # Get usage stats (last 30 days)
        usage_result = await db.execute(
            select(
                func.count(UsageLog.id),
                func.coalesce(func.sum(UsageLog.cost_cents), 0)
            )
            .where(UsageLog.service_id == service.id)
        )
        usage_row = usage_result.first()
        request_count = usage_row[0] if usage_row else 0
        total_cost_cents = usage_row[1] if usage_row else 0

        services_with_info.append({
            "service": service,
            "team_name": service.team.name if service.team else None,
            "key_count": key_count,
            "request_count": request_count,
            "total_cost": total_cost_cents / 100,
        })

    return templates.TemplateResponse(
        request,
        "services.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "services_with_info": services_with_info,
            "teams": teams,
            "is_platform_admin": is_platform_admin,
        },
    )


@router.get("/services/{service_id}")
async def service_detail(
    service_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Service detail page."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)
    groups = await get_user_groups(user.id, ctx.active_org_id, db) if ctx.active_org_id else []
    is_platform_admin = getattr(user, 'is_platform_admin', False)

    # Get the service
    service_result = await db.execute(
        select(Service)
        .where(Service.id == service_id, Service.deleted_at.is_(None))
        .options(selectinload(Service.team))
    )
    service = service_result.scalar_one_or_none()

    if not service:
        return RedirectResponse(url="/services", status_code=303)

    # Check access (platform admin or same org)
    if not is_platform_admin and service.organization_id != ctx.active_org_id:
        return RedirectResponse(url="/services", status_code=303)

    # Get API keys for this service
    keys_result = await db.execute(
        select(APIKey)
        .where(APIKey.service_id == service_id)
        .order_by(APIKey.created_at.desc())
    )
    api_keys = list(keys_result.scalars().all())

    # Get usage logs for this service (recent)
    usage_result = await db.execute(
        select(UsageLog)
        .where(UsageLog.service_id == service_id)
        .order_by(UsageLog.created_at.desc())
        .limit(50)
    )
    usage_logs = list(usage_result.scalars().all())

    # Get usage summary
    summary_result = await db.execute(
        select(
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.cost_cents), 0),
            func.coalesce(func.sum(UsageLog.input_tokens), 0),
            func.coalesce(func.sum(UsageLog.output_tokens), 0)
        )
        .where(UsageLog.service_id == service_id)
    )
    summary_row = summary_result.first()

    return templates.TemplateResponse(
        request,
        "service_detail.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "service": service,
            "api_keys": api_keys,
            "usage_logs": usage_logs,
            "total_requests": summary_row[0] if summary_row else 0,
            "total_cost": (summary_row[1] or 0) / 100,
            "total_input_tokens": summary_row[2] or 0,
            "total_output_tokens": summary_row[3] or 0,
            "is_platform_admin": is_platform_admin,
        },
    )


@router.post("/services/{service_id}/suspend")
async def suspend_service(
    service_id: str,
    request: Request,
    reason: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Suspend a service."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    is_platform_admin = getattr(ctx.user, 'is_platform_admin', False)
    if not is_platform_admin:
        return RedirectResponse(url=f"/services/{service_id}?error=no_permission", status_code=303)

    # Get and suspend the service
    service_result = await db.execute(
        select(Service).where(Service.id == service_id)
    )
    service = service_result.scalar_one_or_none()

    if service:
        service.status = "suspended"
        service.suspended_at = utc_now()
        service.suspended_reason = reason
        service.suspended_by_user_id = ctx.user.id
        await db.commit()

    return RedirectResponse(url=f"/services/{service_id}", status_code=303)


@router.post("/services/{service_id}/unsuspend")
async def unsuspend_service(
    service_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Unsuspend a service."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    is_platform_admin = getattr(ctx.user, 'is_platform_admin', False)
    if not is_platform_admin:
        return RedirectResponse(url=f"/services/{service_id}?error=no_permission", status_code=303)

    # Get and unsuspend the service
    service_result = await db.execute(
        select(Service).where(Service.id == service_id)
    )
    service = service_result.scalar_one_or_none()

    if service:
        service.status = "active"
        service.suspended_at = None
        service.suspended_reason = None
        service.suspended_by_user_id = None
        await db.commit()

    return RedirectResponse(url=f"/services/{service_id}", status_code=303)


@router.post("/services/create")
async def create_service(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    team_id: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Create a new service (platform admin only)."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    is_platform_admin = getattr(ctx.user, 'is_platform_admin', False)
    if not is_platform_admin:
        return RedirectResponse(url="/services?error=no_permission", status_code=303)

    if not ctx.active_org_id:
        return RedirectResponse(url="/services?error=no_org", status_code=303)

    # Check if service name already exists in org
    existing = await db.execute(
        select(Service).where(
            Service.organization_id == ctx.active_org_id,
            Service.name == name.strip()
        )
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(url="/services?error=exists", status_code=303)

    # Create service
    service = Service(
        organization_id=ctx.active_org_id,
        name=name.strip(),
        description=description.strip() if description else None,
        team_id=team_id if team_id else None,
        status="active",
        created_by_user_id=ctx.user.id,
    )
    db.add(service)
    await db.commit()

    return RedirectResponse(url=f"/services/{service.id}", status_code=303)


@router.post("/services/{service_id}/issue-key")
async def issue_service_key(
    service_id: str,
    request: Request,
    key_name: str = Form("Default"),
    environment: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Issue a new API key for a service (platform admin only)."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    is_platform_admin = getattr(ctx.user, 'is_platform_admin', False)
    if not is_platform_admin:
        return RedirectResponse(url=f"/services/{service_id}?error=no_permission", status_code=303)

    # Get service
    service_result = await db.execute(
        select(Service).where(Service.id == service_id)
    )
    service = service_result.scalar_one_or_none()
    if not service:
        return RedirectResponse(url="/services", status_code=303)

    # Get a group for the key (use first group in org)
    group_result = await db.execute(
        select(Group).where(Group.organization_id == service.organization_id).limit(1)
    )
    group = group_result.scalar_one_or_none()
    if not group:
        return RedirectResponse(url=f"/services/{service_id}?error=no_group", status_code=303)

    # Generate API key
    full_key, key_hash, key_prefix = generate_api_key()

    api_key = APIKey(
        user_id=ctx.user.id,
        group_id=group.id,
        service_id=service_id,
        name=key_name.strip() if key_name else "Default",
        key_hash=key_hash,
        key_prefix=key_prefix,
        environment=environment.strip() if environment else None,
        is_system=False,
    )
    db.add(api_key)
    await db.commit()

    # Store the full key in session for one-time display
    # We'll use query param to show it (not ideal but simple)
    return RedirectResponse(
        url=f"/services/{service_id}?new_key={full_key}&key_name={key_name}",
        status_code=303
    )
