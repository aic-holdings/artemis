"""
Public pages: landing, login, register, settings.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.auth_routes import get_current_user, require_user, get_user_organizations, get_user_groups
from app.services.organization_service import OrganizationService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


def is_localhost_request(request: Request) -> bool:
    """Check if request is from localhost."""
    host = request.headers.get("host", "")
    return host.startswith("localhost") or host.startswith("127.0.0.1") or host.startswith("0.0.0.0")


@router.get("/")
async def landing(request: Request, db: AsyncSession = Depends(get_db)):
    """Landing page - redirects to dashboard in localhost mode."""
    from app.config import settings
    if settings.LOCALHOST_MODE and is_localhost_request(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    ctx = await get_current_user(request, db)
    user = ctx.user if ctx else None
    active_org = ctx.active_org if ctx else None
    active_group = ctx.active_group if ctx else None
    organizations = await get_user_organizations(user.id, db) if user else []
    groups = await get_user_groups(user.id, ctx.active_org_id, db) if user and ctx.active_org_id else []
    return templates.TemplateResponse(request, "landing.html", {
        "user": user,
        "active_org": active_org,
        "active_group": active_group,
        "organizations": organizations,
        "groups": groups,
    })


@router.get("/login")
async def login_page(request: Request, error: str = None):
    """Login page - redirects to dashboard in localhost mode."""
    from app.config import settings
    if settings.LOCALHOST_MODE and is_localhost_request(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html", {
        "error": error,
        "sso_enabled": settings.SSO_ENABLED,
    })


@router.get("/register")
async def register_page(request: Request, error: str = None):
    """Register page - redirects to dashboard in localhost mode."""
    from app.config import settings
    if settings.LOCALHOST_MODE and is_localhost_request(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"error": error})


@router.get("/settings")
async def settings_page(request: Request, error: str = None, db: AsyncSession = Depends(get_db)):
    """Settings page with org switcher."""
    ctx = await require_user(request, db)
    organizations = await get_user_organizations(ctx.user.id, db)
    groups = await get_user_groups(ctx.user.id, ctx.active_org_id, db) if ctx.active_org_id else []

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": ctx.user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "error": error,
        },
    )


@router.post("/load-demo-data")
async def load_demo_data(request: Request, db: AsyncSession = Depends(get_db)):
    """Load demo organization with sample API keys and usage data."""
    from app.services.demo_data_service import load_demo_data as do_load_demo_data

    ctx = await require_user(request, db)
    await do_load_demo_data(ctx.user, db)

    return RedirectResponse(url="/settings", status_code=303)


@router.post("/create-org")
async def create_org(request: Request, db: AsyncSession = Depends(get_db)):
    """Create a new organization."""
    ctx = await require_user(request, db)

    form = await request.form()
    name = form.get("name", "").strip()

    if not name:
        # Redirect back with error
        return RedirectResponse(url="/settings?error=Organization+name+required", status_code=303)

    org_service = OrganizationService(db)

    try:
        org, _ = await org_service.create(name=name, owner_id=ctx.user.id)
        # Switch to the new org
        response = RedirectResponse(url="/settings", status_code=303)
        response.set_cookie("active_org_id", str(org.id), httponly=True, samesite="lax")
        return response
    except ValueError as e:
        error_msg = str(e).replace(" ", "+")
        return RedirectResponse(url=f"/settings?error={error_msg}", status_code=303)


# =============================================================================
# Frontend Error Logging (localhost mode only)
# =============================================================================


class FrontendErrorLog(BaseModel):
    """Schema for frontend error log entries."""
    level: str = "error"  # error, warn, info, debug
    message: str
    error_type: Optional[str] = None
    stack_trace: Optional[str] = None
    page: Optional[str] = None
    component: Optional[str] = None
    metadata: Optional[dict] = None


@router.post("/api/log-error")
async def log_frontend_error(
    request: Request,
    error_log: FrontendErrorLog,
    db: AsyncSession = Depends(get_db),
):
    """
    Log frontend errors to the database (localhost mode only).

    This allows debugging frontend errors alongside backend logs
    with auto-timestamps in the app_logs table.
    """
    from app.config import settings
    from app.models import AppLog

    # Only accept logs in localhost mode
    if not (settings.LOCALHOST_MODE and is_localhost_request(request)):
        return JSONResponse({"error": "Endpoint only available in localhost mode"}, status_code=403)

    # Create the log entry
    log_entry = AppLog(
        source="frontend",
        level=error_log.level,
        message=error_log.message,
        error_type=error_log.error_type,
        stack_trace=error_log.stack_trace,
        page=error_log.page,
        component=error_log.component,
        user_agent=request.headers.get("user-agent"),
        extra_data=error_log.metadata,
    )

    db.add(log_entry)
    await db.commit()

    # Also log to Python logger for immediate visibility
    logger.error(
        f"[FRONTEND] {error_log.level.upper()}: {error_log.message}",
        extra={
            "source": "frontend",
            "error_type": error_log.error_type,
            "page": error_log.page,
            "component": error_log.component,
        }
    )

    return JSONResponse({"status": "logged", "id": log_entry.id})
