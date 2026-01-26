"""
Agent-friendly API endpoints.

Provides machine-readable metadata and status for AI agents:
- /v1/models - Discoverable model list with capabilities and costs
- /v1/budget - Budget and rate limit status
- Rich error taxonomy for programmatic handling
"""
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import APIKey, UsageLog, Group
from app.providers.models import PROVIDER_MODELS, PROVIDER_NAMES
from app.providers.pricing import FALLBACK_PRICING, get_fallback_pricing
from app.config import settings

router = APIRouter()


# Model capabilities by provider/model
MODEL_CAPABILITIES = {
    "openai": {
        "gpt-4o": ["chat", "vision", "function_calling", "json_mode"],
        "gpt-4o-mini": ["chat", "vision", "function_calling", "json_mode"],
        "gpt-4-turbo": ["chat", "vision", "function_calling", "json_mode"],
        "o1": ["chat", "reasoning"],
        "o1-mini": ["chat", "reasoning"],
        "o3-mini": ["chat", "reasoning"],
    },
    "anthropic": {
        "claude-sonnet-4": ["chat", "vision", "function_calling"],
        "claude-opus-4": ["chat", "vision", "function_calling"],
        "claude-3-5-sonnet-latest": ["chat", "vision", "function_calling"],
        "claude-3-5-haiku-20241022": ["chat", "vision", "function_calling"],
        "claude-3-opus-20240229": ["chat", "vision", "function_calling"],
    },
    "google": {
        "gemini-2.5-pro": ["chat", "vision", "function_calling", "grounding"],
        "gemini-2.5-flash": ["chat", "vision", "function_calling"],
        "gemini-1.5-pro": ["chat", "vision", "function_calling"],
        "gemini-1.5-flash": ["chat", "vision", "function_calling"],
    },
    "perplexity": {
        "llama-3.1-sonar-small-128k-online": ["chat", "web_search"],
        "llama-3.1-sonar-large-128k-online": ["chat", "web_search"],
        "llama-3.1-sonar-huge-128k-online": ["chat", "web_search"],
    },
}

# Context windows by model
MODEL_CONTEXT_WINDOWS = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "o1": 200000,
    "o1-mini": 128000,
    "o3-mini": 200000,
    "claude-sonnet-4": 200000,
    "claude-opus-4": 200000,
    "claude-3-5-sonnet-latest": 200000,
    "claude-3-5-haiku-20241022": 200000,
    "claude-3-opus-20240229": 200000,
    "gemini-2.5-pro": 1000000,
    "gemini-2.5-flash": 1000000,
    "gemini-1.5-pro": 2000000,
    "gemini-1.5-flash": 1000000,
    "llama-3.1-sonar-small-128k-online": 128000,
    "llama-3.1-sonar-large-128k-online": 128000,
    "llama-3.1-sonar-huge-128k-online": 128000,
}

# Model tiers for agent selection
MODEL_TIERS = {
    "draft": [
        {"provider": "openai", "model": "gpt-4o-mini"},
        {"provider": "anthropic", "model": "claude-3-5-haiku-20241022"},
        {"provider": "google", "model": "gemini-2.5-flash"},
    ],
    "standard": [
        {"provider": "openai", "model": "gpt-4o"},
        {"provider": "anthropic", "model": "claude-3-5-sonnet-latest"},
        {"provider": "google", "model": "gemini-2.5-pro"},
    ],
    "premium": [
        {"provider": "anthropic", "model": "claude-opus-4"},
        {"provider": "openai", "model": "o1"},
        {"provider": "anthropic", "model": "claude-sonnet-4"},
    ],
    "reasoning": [
        {"provider": "openai", "model": "o1"},
        {"provider": "openai", "model": "o3-mini"},
        {"provider": "openai", "model": "o1-mini"},
    ],
    "web_search": [
        {"provider": "perplexity", "model": "llama-3.1-sonar-large-128k-online"},
        {"provider": "perplexity", "model": "llama-3.1-sonar-huge-128k-online"},
    ],
}


async def validate_api_key(
    api_key: str,
    db: AsyncSession,
) -> tuple[Optional[APIKey], Optional[str]]:
    """Validate an Artemis API key and return the key object."""
    if not api_key:
        return None, "Missing API key"

    if api_key.startswith("Bearer "):
        api_key = api_key[7:]

    if not api_key.startswith("art_"):
        return None, "Invalid API key format"

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    result = await db.execute(
        select(APIKey)
        .options(selectinload(APIKey.group))
        .where(APIKey.key_hash == key_hash, APIKey.revoked_at.is_(None))
    )
    api_key_obj = result.scalar_one_or_none()

    if not api_key_obj:
        return None, "Invalid API key"

    api_key_obj.last_used_at = datetime.now(timezone.utc)

    return api_key_obj, None


def make_agent_error(
    code: str,
    message: str,
    category: str,
    status_code: int = 400,
    recovery: dict = None,
    context: dict = None,
) -> JSONResponse:
    """
    Create agent-friendly error response with structured metadata.

    Categories:
    - transient: Retry may succeed (rate limits, timeouts)
    - permanent: Won't succeed without changes (invalid model, auth)
    - policy: Blocked by policy (content filter, budget exceeded)
    - upstream: Provider-side issue
    """
    error_body = {
        "error": {
            "code": code,
            "message": message,
            "category": category,
        }
    }

    if recovery:
        error_body["error"]["recovery"] = recovery
    if context:
        error_body["error"]["context"] = context

    return JSONResponse(status_code=status_code, content=error_body)


@router.get("/v1/models")
async def list_models(
    request: Request,
    provider: Optional[str] = None,
    capability: Optional[str] = None,
    tier: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    List available models with capabilities, costs, and context windows.

    Machine-readable for agent model selection.

    Query params:
    - provider: Filter by provider (openai, anthropic, google, perplexity)
    - capability: Filter by capability (chat, vision, function_calling, reasoning, web_search)
    - tier: Filter by tier (draft, standard, premium, reasoning, web_search)
    """
    auth_header = request.headers.get("Authorization", "")
    api_key_obj, error = await validate_api_key(auth_header, db)
    if error:
        return make_agent_error(
            "INVALID_API_KEY",
            error,
            "permanent",
            401,
            recovery={"action": "check_api_key", "docs": "/guide/api-keys"},
        )

    models = []

    # Build model list from PROVIDER_MODELS
    for prov, model_list in PROVIDER_MODELS.items():
        if provider and prov != provider:
            continue

        for model_id, display_name in model_list:
            # Get capabilities
            caps = MODEL_CAPABILITIES.get(prov, {}).get(model_id, ["chat"])

            # Filter by capability if specified
            if capability and capability not in caps:
                continue

            # Get pricing
            input_price, output_price = get_fallback_pricing(prov, model_id)

            # Get context window
            context_window = MODEL_CONTEXT_WINDOWS.get(model_id, 128000)

            # Determine tier
            model_tier = "standard"
            for t, tier_models in MODEL_TIERS.items():
                for tm in tier_models:
                    if tm["provider"] == prov and tm["model"] == model_id:
                        model_tier = t
                        break

            # Filter by tier if specified
            if tier and model_tier != tier:
                continue

            models.append({
                "id": model_id,
                "provider": prov,
                "provider_name": PROVIDER_NAMES.get(prov, prov),
                "display_name": display_name,
                "capabilities": caps,
                "context_window": context_window,
                "cost": {
                    "input_per_1m_tokens": input_price / 100,  # Convert cents to dollars
                    "output_per_1m_tokens": output_price / 100,
                    "currency": "USD",
                },
                "tier": model_tier,
                "available": True,  # TODO: Check provider key availability
            })

    return {
        "models": models,
        "tiers": MODEL_TIERS,
        "providers": list(PROVIDER_NAMES.keys()),
        "_meta": {
            "pricing_updated": "2024-12-01",
            "note": "Costs are estimates. Actual costs may vary.",
        }
    }


@router.get("/v1/budget")
async def get_budget(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Get current budget status and rate limits.

    Returns remaining budget, spend this period, and rate limit status.
    Agents can use this to make cost-aware decisions.
    """
    auth_header = request.headers.get("Authorization", "")
    api_key_obj, error = await validate_api_key(auth_header, db)
    if error:
        return make_agent_error(
            "INVALID_API_KEY",
            error,
            "permanent",
            401,
        )

    # Get current month's usage
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Sum usage for this API key this month
    result = await db.execute(
        select(
            func.sum(UsageLog.cost_cents).label("total_cost"),
            func.count(UsageLog.id).label("request_count"),
            func.sum(UsageLog.input_tokens).label("total_input_tokens"),
            func.sum(UsageLog.output_tokens).label("total_output_tokens"),
        )
        .where(
            UsageLog.api_key_id == api_key_obj.id,
            UsageLog.created_at >= month_start,
        )
    )
    usage = result.one()

    total_cost_cents = usage.total_cost or 0
    total_cost_usd = total_cost_cents / 100
    request_count = usage.request_count or 0

    # Get budget limit from group if set
    budget_limit = None
    budget_remaining = None
    budget_percentage = None

    if api_key_obj.group:
        # TODO: Add budget_limit_cents to Group model
        # For now, use a placeholder
        budget_limit = 100.00  # $100 default
        budget_remaining = max(0, budget_limit - total_cost_usd)
        budget_percentage = (total_cost_usd / budget_limit * 100) if budget_limit > 0 else 0

    # Build warnings
    warnings = []
    if budget_percentage is not None:
        if budget_percentage >= 95:
            warnings.append({
                "type": "budget_critical",
                "message": f"Budget {budget_percentage:.1f}% used. Consider switching to cheaper models.",
                "severity": "critical",
            })
        elif budget_percentage >= 80:
            warnings.append({
                "type": "budget_low",
                "message": f"Budget {budget_percentage:.1f}% used.",
                "severity": "warning",
            })

    # Calculate reset time (first of next month)
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

    return {
        "budget": {
            "period": "monthly",
            "limit": budget_limit,
            "used": round(total_cost_usd, 4),
            "remaining": round(budget_remaining, 4) if budget_remaining is not None else None,
            "percentage_used": round(budget_percentage, 1) if budget_percentage is not None else None,
            "currency": "USD",
            "resets_at": next_month.isoformat(),
        },
        "usage": {
            "requests_this_period": request_count,
            "input_tokens_this_period": usage.total_input_tokens or 0,
            "output_tokens_this_period": usage.total_output_tokens or 0,
        },
        "rate_limits": {
            "requests_per_minute": 60,  # TODO: Make configurable
            "tokens_per_minute": 100000,
            # TODO: Track actual current rates
        },
        "warnings": warnings,
        "_meta": {
            "api_key_name": api_key_obj.name,
            "group": api_key_obj.group.name if api_key_obj.group else None,
        }
    }


@router.get("/v1/status")
async def get_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Get API status and provider health.

    Agents can use this to check if specific providers are available
    before making requests.
    """
    auth_header = request.headers.get("Authorization", "")
    api_key_obj, error = await validate_api_key(auth_header, db)
    if error:
        return make_agent_error(
            "INVALID_API_KEY",
            error,
            "permanent",
            401,
        )

    # Get provider health from service
    from app.services.provider_health import provider_health

    providers_status = {}
    for provider_id in settings.PROVIDER_URLS.keys():
        health = provider_health.get_provider_health(provider_id)
        providers_status[provider_id] = {
            "available": health.get("status") != "down",
            "status": health.get("status", "unknown"),
            "latency_avg_ms": health.get("avg_latency_ms"),
            "error_rate": health.get("error_rate"),
            "last_success": health.get("last_success"),
            "last_failure": health.get("last_failure"),
        }

    return {
        "status": "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "providers": providers_status,
    }


@router.get("/api/usage/breakdown")
async def get_usage_breakdown(
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = 30,
    limit: int = 20,
):
    """
    Get detailed usage breakdown by model, provider, and day.

    Useful for understanding where costs are coming from.

    Parameters:
    - days: Number of days to look back (default 30)
    - limit: Max items per category (default 20)
    """
    auth_header = request.headers.get("Authorization", "")
    api_key_obj, error = await validate_api_key(auth_header, db)
    if error:
        return make_agent_error(
            "INVALID_API_KEY",
            error,
            "permanent",
            401,
        )

    # Calculate period start
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=days)

    # Get all usage logs for this API key in the period
    result = await db.execute(
        select(UsageLog)
        .where(
            UsageLog.api_key_id == api_key_obj.id,
            UsageLog.created_at >= period_start,
        )
        .order_by(UsageLog.created_at.desc())
    )
    logs = result.scalars().all()

    # Aggregate by model
    by_model = {}
    by_provider = {}
    by_day = {}
    recent_requests = []

    for log in logs:
        model = log.model or "unknown"
        provider = log.provider or "unknown"
        day = log.created_at.strftime("%Y-%m-%d")
        cost_usd = (log.cost_cents or 0) / 100
        tokens = (log.input_tokens or 0) + (log.output_tokens or 0)

        # By model
        if model not in by_model:
            by_model[model] = {"requests": 0, "cost_usd": 0, "tokens": 0}
        by_model[model]["requests"] += 1
        by_model[model]["cost_usd"] += cost_usd
        by_model[model]["tokens"] += tokens

        # By provider
        if provider not in by_provider:
            by_provider[provider] = {"requests": 0, "cost_usd": 0, "tokens": 0}
        by_provider[provider]["requests"] += 1
        by_provider[provider]["cost_usd"] += cost_usd
        by_provider[provider]["tokens"] += tokens

        # By day
        if day not in by_day:
            by_day[day] = {"requests": 0, "cost_usd": 0, "tokens": 0}
        by_day[day]["requests"] += 1
        by_day[day]["cost_usd"] += cost_usd
        by_day[day]["tokens"] += tokens

        # Recent requests (last N)
        if len(recent_requests) < limit:
            recent_requests.append({
                "timestamp": log.created_at.isoformat(),
                "model": model,
                "provider": provider,
                "input_tokens": log.input_tokens or 0,
                "output_tokens": log.output_tokens or 0,
                "cost_usd": cost_usd,
                "latency_ms": log.latency_ms,
                "app_id": log.app_id,
            })

    # Sort and limit
    by_model_sorted = dict(sorted(by_model.items(), key=lambda x: x[1]["cost_usd"], reverse=True)[:limit])
    by_provider_sorted = dict(sorted(by_provider.items(), key=lambda x: x[1]["cost_usd"], reverse=True)[:limit])
    by_day_sorted = dict(sorted(by_day.items(), reverse=True)[:limit])

    # Round costs
    for d in [by_model_sorted, by_provider_sorted, by_day_sorted]:
        for k, v in d.items():
            v["cost_usd"] = round(v["cost_usd"], 4)

    total_cost = sum(v["cost_usd"] for v in by_model_sorted.values())
    total_requests = sum(v["requests"] for v in by_model_sorted.values())
    total_tokens = sum(v["tokens"] for v in by_model_sorted.values())

    return {
        "period": {
            "start": period_start.isoformat(),
            "end": now.isoformat(),
            "days": days,
        },
        "totals": {
            "requests": total_requests,
            "cost_usd": round(total_cost, 4),
            "tokens": total_tokens,
        },
        "by_model": by_model_sorted,
        "by_provider": by_provider_sorted,
        "by_day": by_day_sorted,
        "recent_requests": recent_requests,
        "_meta": {
            "api_key_name": api_key_obj.name,
            "group": api_key_obj.group.name if api_key_obj.group else None,
        }
    }
