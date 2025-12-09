"""
Health status monitoring routes.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.auth_routes import get_current_user, get_user_organizations, get_user_groups
from app.services.provider_health import provider_health

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/health-status")
async def health_status_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Provider health status page."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)
    groups = await get_user_groups(user.id, ctx.active_org_id, db) if ctx.active_org_id else []

    # Get health summary from the provider health tracker
    health_summary = provider_health.get_summary()

    return templates.TemplateResponse(
        request,
        "health_status.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "health_summary": health_summary,
            "providers": health_summary.get("providers", {}),
            "unhealthy_providers": health_summary.get("unhealthy_providers", []),
            "degraded_providers": health_summary.get("degraded_providers", []),
            "all_healthy": health_summary.get("all_healthy", True),
        },
    )


@router.get("/api/health-status")
async def health_status_api(request: Request, db: AsyncSession = Depends(get_db)):
    """API endpoint for health status (for auto-refresh)."""
    user = await get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    return JSONResponse(provider_health.get_summary())
