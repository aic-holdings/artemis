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

    # ===========================================
    # PHASE 1: Teams & Services Data Model
    # ===========================================

    # Create teams table
    try:
        check_table = await db.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'teams'
        """))
        table_exists = check_table.fetchone() is not None

        if table_exists:
            results.append({"table": "teams", "status": "already_exists"})
        else:
            await db.execute(text("""
                CREATE TABLE teams (
                    id VARCHAR PRIMARY KEY,
                    organization_id VARCHAR NOT NULL REFERENCES organizations(id),
                    name VARCHAR NOT NULL,
                    description TEXT,
                    status VARCHAR NOT NULL DEFAULT 'active',
                    created_by_user_id VARCHAR REFERENCES users(id),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    deleted_at TIMESTAMPTZ,
                    UNIQUE(organization_id, name)
                )
            """))
            await db.execute(text("CREATE INDEX ix_teams_organization_id ON teams(organization_id)"))
            await db.commit()
            results.append({"table": "teams", "status": "created"})
    except Exception as e:
        results.append({"error": f"teams: {str(e)}"})

    # Create team_members table
    try:
        check_table = await db.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'team_members'
        """))
        table_exists = check_table.fetchone() is not None

        if table_exists:
            results.append({"table": "team_members", "status": "already_exists"})
        else:
            await db.execute(text("""
                CREATE TABLE team_members (
                    id VARCHAR PRIMARY KEY,
                    team_id VARCHAR NOT NULL REFERENCES teams(id),
                    user_id VARCHAR NOT NULL REFERENCES users(id),
                    role VARCHAR NOT NULL DEFAULT 'member',
                    added_at TIMESTAMPTZ DEFAULT NOW(),
                    added_by_user_id VARCHAR REFERENCES users(id),
                    UNIQUE(team_id, user_id)
                )
            """))
            await db.execute(text("CREATE INDEX ix_team_members_team_id ON team_members(team_id)"))
            await db.execute(text("CREATE INDEX ix_team_members_user_id ON team_members(user_id)"))
            await db.commit()
            results.append({"table": "team_members", "status": "created"})
    except Exception as e:
        results.append({"error": f"team_members: {str(e)}"})

    # Create services table
    try:
        check_table = await db.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'services'
        """))
        table_exists = check_table.fetchone() is not None

        if table_exists:
            results.append({"table": "services", "status": "already_exists"})
        else:
            await db.execute(text("""
                CREATE TABLE services (
                    id VARCHAR PRIMARY KEY,
                    organization_id VARCHAR NOT NULL REFERENCES organizations(id),
                    team_id VARCHAR REFERENCES teams(id),
                    name VARCHAR NOT NULL,
                    description TEXT,
                    status VARCHAR NOT NULL DEFAULT 'active',
                    suspended_at TIMESTAMPTZ,
                    suspended_reason TEXT,
                    suspended_by_user_id VARCHAR REFERENCES users(id),
                    alert_threshold_cents INTEGER,
                    monthly_budget_cents INTEGER,
                    created_by_user_id VARCHAR REFERENCES users(id),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    deleted_at TIMESTAMPTZ,
                    UNIQUE(organization_id, name)
                )
            """))
            await db.execute(text("CREATE INDEX ix_services_organization_id ON services(organization_id)"))
            await db.execute(text("CREATE INDEX ix_services_team_id ON services(team_id)"))
            await db.commit()
            results.append({"table": "services", "status": "created"})
    except Exception as e:
        results.append({"error": f"services: {str(e)}"})

    # Add new columns to api_keys
    api_key_columns = [
        ("service_id", "VARCHAR REFERENCES services(id)"),
        ("environment", "VARCHAR"),
        ("expires_at", "TIMESTAMPTZ"),
        ("rotation_group_id", "VARCHAR"),
    ]
    for col_name, col_type in api_key_columns:
        try:
            check_col = await db.execute(text(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'api_keys' AND column_name = '{col_name}'
            """))
            col_exists = check_col.fetchone() is not None

            if col_exists:
                results.append({"column": f"api_keys.{col_name}", "status": "already_exists"})
            else:
                await db.execute(text(f"ALTER TABLE api_keys ADD COLUMN {col_name} {col_type}"))
                await db.commit()
                results.append({"column": f"api_keys.{col_name}", "status": "added"})
        except Exception as e:
            results.append({"error": f"api_keys.{col_name}: {str(e)}"})

    # Add indexes to api_keys
    try:
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_api_keys_service_id ON api_keys(service_id)"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_api_keys_rotation_group_id ON api_keys(rotation_group_id)"))
        await db.commit()
        results.append({"indexes": "api_keys indexes created/verified"})
    except Exception as e:
        results.append({"error": f"api_keys indexes: {str(e)}"})

    # Add new columns to usage_logs (denormalized snapshots - NO foreign keys)
    usage_log_columns = [
        ("service_id", "VARCHAR"),
        ("team_id_at_request", "VARCHAR"),
        ("api_key_created_by_user_id", "VARCHAR"),
    ]
    for col_name, col_type in usage_log_columns:
        try:
            check_col = await db.execute(text(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'usage_logs' AND column_name = '{col_name}'
            """))
            col_exists = check_col.fetchone() is not None

            if col_exists:
                results.append({"column": f"usage_logs.{col_name}", "status": "already_exists"})
            else:
                await db.execute(text(f"ALTER TABLE usage_logs ADD COLUMN {col_name} {col_type}"))
                await db.commit()
                results.append({"column": f"usage_logs.{col_name}", "status": "added"})
        except Exception as e:
            results.append({"error": f"usage_logs.{col_name}: {str(e)}"})

    # Add indexes to usage_logs
    try:
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_usage_logs_service_id ON usage_logs(service_id)"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_usage_logs_team_id_at_request ON usage_logs(team_id_at_request)"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_usage_logs_api_key_created_by_user_id ON usage_logs(api_key_created_by_user_id)"))
        await db.commit()
        results.append({"indexes": "usage_logs indexes created/verified"})
    except Exception as e:
        results.append({"error": f"usage_logs indexes: {str(e)}"})

    # Update alembic version
    try:
        await db.execute(text("""
            UPDATE alembic_version SET version_num = 'f6g7h8i9j0k1'
        """))
        await db.commit()
        results.append({"alembic": "stamped to f6g7h8i9j0k1"})
    except Exception as e:
        results.append({"note": f"alembic stamp: {str(e)}"})

    return JSONResponse({"migrations": results})
