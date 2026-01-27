"""
Team management routes.
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Team, TeamMember, Service, UsageLog, User, utc_now
from app.routers.auth_routes import get_current_user, get_user_organizations, get_user_groups

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/teams")
async def teams_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Teams management page - lists teams in current organization."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)
    groups = await get_user_groups(user.id, ctx.active_org_id, db) if ctx.active_org_id else []

    # Check if user is platform admin
    is_platform_admin = getattr(user, 'is_platform_admin', False)

    # Teams are only relevant when viewing an organization (or platform admin)
    if not ctx.active_org_id and not is_platform_admin:
        return templates.TemplateResponse(
            request,
            "teams.html",
            {
                "user": user,
                "active_org": None,
                "active_group": ctx.active_group,
                "organizations": organizations,
                "groups": groups,
                "teams_with_info": [],
                "is_platform_admin": is_platform_admin,
                "error": "Select an organization to manage teams.",
            },
        )

    # Get teams for this org
    if is_platform_admin and not ctx.active_org_id:
        # Platform admin with no org selected - show all teams
        teams_result = await db.execute(
            select(Team)
            .where(Team.deleted_at.is_(None))
            .options(selectinload(Team.organization))
            .order_by(Team.name)
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

    # Get stats for each team
    teams_with_info = []
    for team in teams:
        # Count team members
        member_count_result = await db.execute(
            select(func.count(TeamMember.id))
            .where(TeamMember.team_id == team.id)
        )
        member_count = member_count_result.scalar() or 0

        # Count services owned by this team
        service_count_result = await db.execute(
            select(func.count(Service.id))
            .where(Service.team_id == team.id, Service.deleted_at.is_(None))
        )
        service_count = service_count_result.scalar() or 0

        # Get usage stats for team (via denormalized team_id_at_request)
        usage_result = await db.execute(
            select(
                func.count(UsageLog.id),
                func.coalesce(func.sum(UsageLog.cost_cents), 0)
            )
            .where(UsageLog.team_id_at_request == team.id)
        )
        usage_row = usage_result.first()
        request_count = usage_row[0] if usage_row else 0
        total_cost_cents = usage_row[1] if usage_row else 0

        teams_with_info.append({
            "team": team,
            "org_name": team.organization.name if hasattr(team, 'organization') and team.organization else None,
            "member_count": member_count,
            "service_count": service_count,
            "request_count": request_count,
            "total_cost": total_cost_cents / 100,
        })

    return templates.TemplateResponse(
        request,
        "teams.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "teams_with_info": teams_with_info,
            "is_platform_admin": is_platform_admin,
        },
    )


@router.get("/teams/{team_id}")
async def team_detail(
    team_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Team detail page."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)
    groups = await get_user_groups(user.id, ctx.active_org_id, db) if ctx.active_org_id else []
    is_platform_admin = getattr(user, 'is_platform_admin', False)

    # Get the team
    team_result = await db.execute(
        select(Team)
        .where(Team.id == team_id, Team.deleted_at.is_(None))
        .options(selectinload(Team.organization))
    )
    team = team_result.scalar_one_or_none()

    if not team:
        return RedirectResponse(url="/teams", status_code=303)

    # Check access (platform admin or same org)
    if not is_platform_admin and team.organization_id != ctx.active_org_id:
        return RedirectResponse(url="/teams", status_code=303)

    # Get team members with user info
    members_result = await db.execute(
        select(TeamMember)
        .where(TeamMember.team_id == team_id)
        .options(selectinload(TeamMember.user))
        .order_by(TeamMember.added_at.desc())
    )
    team_members = list(members_result.scalars().all())

    # Get services owned by this team
    services_result = await db.execute(
        select(Service)
        .where(Service.team_id == team_id, Service.deleted_at.is_(None))
        .order_by(Service.name)
    )
    services = list(services_result.scalars().all())

    # Get usage logs for this team (recent)
    usage_result = await db.execute(
        select(UsageLog)
        .where(UsageLog.team_id_at_request == team_id)
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
        .where(UsageLog.team_id_at_request == team_id)
    )
    summary_row = summary_result.first()

    return templates.TemplateResponse(
        request,
        "team_detail.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "team": team,
            "team_members": team_members,
            "services": services,
            "usage_logs": usage_logs,
            "total_requests": summary_row[0] if summary_row else 0,
            "total_cost": (summary_row[1] or 0) / 100,
            "total_input_tokens": summary_row[2] or 0,
            "total_output_tokens": summary_row[3] or 0,
            "is_platform_admin": is_platform_admin,
        },
    )


@router.post("/teams/create")
async def create_team(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Create a new team (platform admin only)."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    is_platform_admin = getattr(ctx.user, 'is_platform_admin', False)
    if not is_platform_admin:
        return RedirectResponse(url="/teams?error=no_permission", status_code=303)

    if not ctx.active_org_id:
        return RedirectResponse(url="/teams?error=no_org", status_code=303)

    # Check if team name already exists in org
    existing = await db.execute(
        select(Team).where(
            Team.organization_id == ctx.active_org_id,
            Team.name == name.strip()
        )
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(url="/teams?error=exists", status_code=303)

    # Create team
    team = Team(
        organization_id=ctx.active_org_id,
        name=name.strip(),
        description=description.strip() if description else None,
        status="active",
        created_by_user_id=ctx.user.id,
    )
    db.add(team)
    await db.commit()

    return RedirectResponse(url=f"/teams/{team.id}", status_code=303)


@router.post("/teams/{team_id}/edit")
async def edit_team(
    team_id: str,
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Edit a team (platform admin only)."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    is_platform_admin = getattr(ctx.user, 'is_platform_admin', False)
    if not is_platform_admin:
        return RedirectResponse(url=f"/teams/{team_id}?error=no_permission", status_code=303)

    # Get team
    team_result = await db.execute(
        select(Team).where(Team.id == team_id)
    )
    team = team_result.scalar_one_or_none()
    if not team:
        return RedirectResponse(url="/teams", status_code=303)

    # Check if new name conflicts with another team (if name changed)
    if name.strip() != team.name:
        existing = await db.execute(
            select(Team).where(
                Team.organization_id == team.organization_id,
                Team.name == name.strip(),
                Team.id != team_id
            )
        )
        if existing.scalar_one_or_none():
            return RedirectResponse(url=f"/teams/{team_id}?error=name_exists", status_code=303)

    # Update team
    team.name = name.strip()
    team.description = description.strip() if description else None
    await db.commit()

    return RedirectResponse(url=f"/teams/{team_id}?success=updated", status_code=303)


@router.post("/teams/{team_id}/archive")
async def archive_team(
    team_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Archive a team (soft delete)."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    is_platform_admin = getattr(ctx.user, 'is_platform_admin', False)
    if not is_platform_admin:
        return RedirectResponse(url=f"/teams/{team_id}?error=no_permission", status_code=303)

    # Get and archive the team
    team_result = await db.execute(
        select(Team).where(Team.id == team_id)
    )
    team = team_result.scalar_one_or_none()

    if team:
        team.status = "archived"
        team.deleted_at = utc_now()
        await db.commit()

    return RedirectResponse(url="/teams", status_code=303)


@router.post("/teams/{team_id}/restore")
async def restore_team(
    team_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Restore an archived team."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    is_platform_admin = getattr(ctx.user, 'is_platform_admin', False)
    if not is_platform_admin:
        return RedirectResponse(url=f"/teams/{team_id}?error=no_permission", status_code=303)

    # Get and restore the team
    team_result = await db.execute(
        select(Team).where(Team.id == team_id)
    )
    team = team_result.scalar_one_or_none()

    if team:
        team.status = "active"
        team.deleted_at = None
        await db.commit()

    return RedirectResponse(url=f"/teams/{team_id}", status_code=303)
