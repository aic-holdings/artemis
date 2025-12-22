import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import init_db

# Check if we're in development mode
IS_DEV_MODE = os.getenv("LOCALHOST_MODE", "").lower() in ("true", "1", "yes")

templates = Jinja2Templates(directory="app/templates")

# Add global template variables
templates.env.globals["localhost_mode"] = IS_DEV_MODE
from app.routers import (
    auth_routes,
    proxy_routes,
    pages,
    analytics,
    api_keys,
    api_v1_keys,
    provider_keys,
    logs,
    health,
    guide,
    groups,
    chat,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and load health records on startup."""
    await init_db()

    # CRITICAL: Verify encryption key can decrypt existing provider keys
    # This prevents silent failures where keys exist but can't be used
    from app.services.encryption_validator import validate_encryption_key
    encryption_status = await validate_encryption_key()
    if encryption_status["status"] == "error":
        print("=" * 60)
        print("CRITICAL: ENCRYPTION_KEY MISMATCH DETECTED")
        print("=" * 60)
        print(f"Error: {encryption_status['error']}")
        print(f"Affected keys: {encryption_status.get('affected_count', 'unknown')}")
        print("")
        print("Provider keys exist but cannot be decrypted.")
        print("This usually means ENCRYPTION_KEY was changed without migration.")
        print("")
        print("To fix:")
        print("1. Restore the original ENCRYPTION_KEY, OR")
        print("2. Delete all provider keys and re-add them")
        print("=" * 60)
        # Store status for health check
        app.state.encryption_status = encryption_status
    else:
        app.state.encryption_status = encryption_status
        if encryption_status["status"] == "warning":
            print(f"Warning: {encryption_status.get('message', 'Encryption validation warning')}")

    # Load provider health records from database
    from app.services.provider_health import provider_health
    await provider_health.load_from_database()

    yield

    # Cleanup old health records on shutdown
    await provider_health.cleanup_old_records()


app = FastAPI(
    title="Artemis",
    description="AI Management Platform - Unified proxy for LLM API calls",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(auth_routes.router, tags=["auth"])
app.include_router(pages.router, tags=["pages"])
app.include_router(analytics.router, tags=["analytics"])
app.include_router(api_keys.router, tags=["api-keys"])
app.include_router(provider_keys.router, tags=["provider-keys"])
app.include_router(logs.router, tags=["logs"])
app.include_router(health.router, tags=["health"])
app.include_router(guide.router, tags=["guide"])
app.include_router(groups.router, tags=["groups"])
app.include_router(chat.router, tags=["chat"])
app.include_router(api_v1_keys.router, tags=["api-v1"])
app.include_router(proxy_routes.router, tags=["proxy"])


@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint with encryption validation status."""
    from app.config import settings

    # Get encryption status from app state (set during startup)
    encryption_status = getattr(request.app.state, "encryption_status", None)

    # Determine overall health
    if encryption_status and encryption_status.get("status") == "error":
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    response = {
        "status": overall_status,
        "service": "artemis",
        "version": "1.0.0",
        "auth": {
            "provider": "custom-jwt",
            "sso_enabled": settings.SSO_ENABLED,
            "sso_url": settings.JETTA_SSO_URL if settings.SSO_ENABLED else None,
        },
        "checks": {
            "encryption": encryption_status or {"status": "unknown"},
        }
    }

    return response


@app.get("/test-error")
async def test_error():
    """Test endpoint to trigger an error (dev only)."""
    if not IS_DEV_MODE:
        return {"error": "Not available in production"}
    raise ValueError("This is a test error to verify the error page works!")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler that shows detailed errors in dev mode.
    In production, shows a generic error page.
    """
    error_type = type(exc).__name__
    error_message = str(exc)
    tb = traceback.format_exc()

    # Log the error
    print(f"ERROR: {error_type}: {error_message}")
    print(tb)

    # Get useful request headers for debugging
    user_agent = request.headers.get("user-agent", "Unknown")
    content_type = request.headers.get("content-type", "None")
    referer = request.headers.get("referer", "None")

    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": 500,
            "error_type": error_type,
            "error_message": error_message,
            "traceback": tb,
            "request_method": request.method,
            "request_url": str(request.url),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_dev_mode": IS_DEV_MODE,
            "user_agent": user_agent,
            "content_type": content_type,
            "referer": referer,
        },
        status_code=500,
    )
