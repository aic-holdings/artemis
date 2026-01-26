"""
Health status monitoring routes.
"""
import secrets
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.config import settings
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


@router.post("/api/migrate")
async def run_migration(request: Request, db: AsyncSession = Depends(get_db)):
    """
    One-time migration endpoint to add missing columns.
    Protected by MASTER_API_KEY.

    Call with:
    curl -X POST https://artemis.jettaintelligence.com/api/migrate \
         -H "Authorization: Bearer <MASTER_API_KEY>"
    """
    # Verify master API key
    if not settings.MASTER_API_KEY:
        raise HTTPException(status_code=503, detail="MASTER_API_KEY not configured")

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    provided_key = auth_header[7:]
    if not secrets.compare_digest(provided_key, settings.MASTER_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid master API key")

    results = []

    # Check and add is_service_account column
    try:
        check_col = await db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'is_service_account'
        """))
        col_exists = check_col.fetchone() is not None

        if col_exists:
            results.append({"column": "is_service_account", "status": "already_exists"})
        else:
            await db.execute(text("""
                ALTER TABLE users ADD COLUMN is_service_account BOOLEAN NOT NULL DEFAULT false
            """))
            await db.commit()
            results.append({"column": "is_service_account", "status": "added"})

            # Update alembic version
            await db.execute(text("""
                UPDATE alembic_version SET version_num = 'd4e5f6g7h8i9'
            """))
            await db.commit()
            results.append({"alembic": "stamped to d4e5f6g7h8i9"})
    except Exception as e:
        results.append({"error": str(e)})

    # Check and add is_platform_admin column
    try:
        check_col = await db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'is_platform_admin'
        """))
        col_exists = check_col.fetchone() is not None

        if col_exists:
            results.append({"column": "is_platform_admin", "status": "already_exists"})
        else:
            await db.execute(text("""
                ALTER TABLE users ADD COLUMN is_platform_admin BOOLEAN NOT NULL DEFAULT false
            """))
            await db.commit()
            results.append({"column": "is_platform_admin", "status": "added"})

            # Update alembic version
            await db.execute(text("""
                UPDATE alembic_version SET version_num = 'e5f6g7h8i9j0'
            """))
            await db.commit()
            results.append({"alembic": "stamped to e5f6g7h8i9j0"})
    except Exception as e:
        results.append({"error": f"is_platform_admin: {str(e)}"})

    return JSONResponse({"migrations": results})
