"""
Dashboard analytics routes.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, APIKey, ProviderKey, ProviderAccount, UsageLog, GroupMember, Group, Service, Team
from app.routers.auth_routes import get_current_user, get_user_organizations, get_user_groups
from app.providers.pricing import get_pricing_for_date, get_fallback_pricing_info, UsageTokens, calculate_input_output_costs, FALLBACK_PRICING

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def get_period_start(period: str) -> datetime:
    """Get the start date for a given period filter."""
    now = datetime.now(timezone.utc)

    if period == "7":
        return now - timedelta(days=7)
    elif period == "14":
        return now - timedelta(days=14)
    elif period == "30":
        return now - timedelta(days=30)
    elif period == "qtd":
        # Quarter to date - start of current quarter
        quarter_month = ((now.month - 1) // 3) * 3 + 1
        return datetime(now.year, quarter_month, 1, tzinfo=timezone.utc)
    elif period == "ytd":
        # Year to date - start of current year
        return datetime(now.year, 1, 1, tzinfo=timezone.utc)
    elif period == "itd":
        # Inception to date - beginning of time
        return datetime(2020, 1, 1, tzinfo=timezone.utc)
    else:
        return now - timedelta(days=30)


@router.get("/dashboard")
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    provider: str = None,
    app_id: str = None,
    key_id: str = None,
    provider_key_id: str = None,
    user_id: str = None,
    service_id: str = None,
    team_id: str = None,
    period: str = "30",
):
    """Main dashboard with analytics."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    active_org = ctx.active_org

    # Check if user is platform admin - they see ALL data
    is_platform_admin = getattr(user, 'is_platform_admin', False)

    # Get organizations for dropdown
    if is_platform_admin:
        # Platform admins see ALL organizations
        from app.models import Organization
        all_orgs_result = await db.execute(
            select(Organization).order_by(Organization.name)
        )
        organizations = list(all_orgs_result.scalars().all())
    else:
        organizations = await get_user_organizations(user.id, db)

    # Get filter values
    filter_provider = provider
    filter_app_id = app_id
    filter_key_id = key_id
    filter_provider_key_id = provider_key_id
    filter_user_id = user_id
    filter_service_id = service_id
    filter_team_id = team_id
    valid_periods = ["7", "14", "30", "qtd", "ytd", "itd"]
    filter_period = period if period in valid_periods else "30"

    # Get usage stats for selected period
    period_start = get_period_start(filter_period)

    # Determine which organization's data to show
    # If active_org is set, show that org's data; otherwise show current user's data only
    viewing_org_id = ctx.active_org_id
    viewing_group_id = ctx.active_group_id

    # Track if we're in "All Groups" mode or "Platform Admin" mode
    all_groups_mode = viewing_org_id and not viewing_group_id
    platform_admin_mode = is_platform_admin and not viewing_org_id  # Admin with no org selected = see everything

    # Load services and teams for filter dropdowns
    all_services = []
    all_teams = []
    if is_platform_admin and not viewing_org_id:
        # Platform admins with no org selected see all services and teams
        services_result = await db.execute(
            select(Service).where(Service.deleted_at.is_(None)).order_by(Service.name)
        )
        all_services = list(services_result.scalars().all())
        teams_result = await db.execute(
            select(Team).where(Team.deleted_at.is_(None)).order_by(Team.name)
        )
        all_teams = list(teams_result.scalars().all())
    elif viewing_org_id:
        # Show services and teams for the active organization
        services_result = await db.execute(
            select(Service).where(
                Service.organization_id == viewing_org_id,
                Service.deleted_at.is_(None)
            ).order_by(Service.name)
        )
        all_services = list(services_result.scalars().all())
        teams_result = await db.execute(
            select(Team).where(
                Team.organization_id == viewing_org_id,
                Team.deleted_at.is_(None)
            ).order_by(Team.name)
        )
        all_teams = list(teams_result.scalars().all())

    # Get groups for filter dropdown (if in org context)
    groups = []
    if viewing_org_id:
        if is_platform_admin:
            # Platform admins see all groups in selected org
            groups_result = await db.execute(
                select(Group).where(Group.organization_id == viewing_org_id).order_by(Group.name)
            )
            groups = list(groups_result.scalars().all())
        else:
            groups = await get_user_groups(user.id, viewing_org_id, db)

    # Get group members (for user filter dropdown) - members of the active group or all groups
    group_users = []
    if platform_admin_mode:
        # Platform admin mode - get all users
        all_users_result = await db.execute(
            select(User).order_by(User.email)
        )
        group_users = list(all_users_result.scalars().all())
    elif viewing_group_id:
        # Get all users who are members of this specific group
        group_members_result = await db.execute(
            select(User)
            .join(GroupMember, GroupMember.user_id == User.id)
            .where(GroupMember.group_id == viewing_group_id)
            .order_by(User.email)
        )
        group_users = list(group_members_result.scalars().all())
    elif all_groups_mode:
        # "All Groups" mode - get users from all groups user belongs to
        group_ids = [g.id for g in groups]
        if group_ids:
            # Use subquery to get distinct user IDs first (avoids DISTINCT on JSON columns)
            distinct_user_ids = (
                select(GroupMember.user_id)
                .where(GroupMember.group_id.in_(group_ids))
                .distinct()
                .scalar_subquery()
            )
            group_members_result = await db.execute(
                select(User)
                .where(User.id.in_(distinct_user_ids))
                .order_by(User.email)
            )
            group_users = list(group_members_result.scalars().all())

    # Determine which user(s) to show data for
    if platform_admin_mode:
        # Platform admin sees all - no user filtering unless explicitly filtered
        target_user_ids = None  # Special value meaning "all users"
        if filter_user_id:
            target_user_ids = [filter_user_id]
    elif viewing_group_id:
        # When viewing a specific group, show data for users IN that group
        target_user_ids = [u.id for u in group_users]

        if filter_user_id:
            # Verify the filtered user is in the group
            if filter_user_id in target_user_ids:
                target_user_ids = [filter_user_id]
    elif all_groups_mode:
        # "All Groups" mode - show data for all users in all groups
        target_user_ids = [u.id for u in group_users]

        if filter_user_id:
            # Verify the filtered user is in one of the groups
            if filter_user_id in target_user_ids:
                target_user_ids = [filter_user_id]
    else:
        # No org/group selected - show current user's data only
        target_user_ids = [user.id]

    # Get API keys - filtered by group if in group context
    # Platform admin mode: get ALL keys
    if platform_admin_mode:
        api_key_conditions = []  # No filtering - get all keys
    elif target_user_ids:
        api_key_conditions = [APIKey.user_id.in_(target_user_ids)]
    else:
        api_key_conditions = [APIKey.user_id.in_([user.id])]  # Fallback

    if not platform_admin_mode:
        if viewing_group_id:
            api_key_conditions.append(APIKey.group_id == viewing_group_id)
        elif all_groups_mode:
            # "All Groups" mode - get keys from all groups user belongs to
            group_ids = [g.id for g in groups]
            if group_ids:
                api_key_conditions.append(APIKey.group_id.in_(group_ids))
            else:
                api_key_conditions.append(APIKey.group_id.is_(None))  # Fallback
        else:
            api_key_conditions.append(APIKey.group_id.is_(None))

    # Build API keys query - handle empty conditions for platform admin
    if api_key_conditions:
        all_api_keys_result = await db.execute(
            select(APIKey).where(*api_key_conditions).order_by(APIKey.name)
        )
    else:
        # Platform admin: get ALL keys
        all_api_keys_result = await db.execute(
            select(APIKey).order_by(APIKey.name)
        )
    all_api_keys = all_api_keys_result.scalars().all()

    # Get active API keys for usage lookup
    if api_key_conditions:
        api_keys_result = await db.execute(
            select(APIKey).where(*api_key_conditions, APIKey.revoked_at.is_(None))
        )
    else:
        api_keys_result = await db.execute(
            select(APIKey).where(APIKey.revoked_at.is_(None))
        )
    api_keys = api_keys_result.scalars().all()
    api_key_ids = [k.id for k in api_keys]

    # If filtering by specific API key, use that
    if filter_key_id:
        if api_key_conditions:
            key_check = await db.execute(
                select(APIKey).where(APIKey.id == filter_key_id, *api_key_conditions)
            )
        else:
            key_check = await db.execute(
                select(APIKey).where(APIKey.id == filter_key_id)
            )
        if key_check.scalar_one_or_none():
            api_key_ids = [filter_key_id]

    # Get provider keys - filtered by group if in group context
    # ProviderKey now goes through ProviderAccount for group_id and provider_id
    if platform_admin_mode:
        # Platform admin: get ALL provider keys
        provider_keys_result = await db.execute(
            select(ProviderKey)
            .join(ProviderAccount)
            .order_by(ProviderAccount.provider_id, ProviderKey.name)
        )
    elif viewing_group_id:
        provider_keys_result = await db.execute(
            select(ProviderKey)
            .join(ProviderAccount)
            .where(
                ProviderKey.user_id.in_(target_user_ids),
                ProviderAccount.group_id == viewing_group_id
            )
            .order_by(ProviderAccount.provider_id, ProviderKey.name)
        )
    elif all_groups_mode:
        # "All Groups" mode - get provider keys from all groups user belongs to
        group_ids = [g.id for g in groups]
        if group_ids:
            provider_keys_result = await db.execute(
                select(ProviderKey)
                .join(ProviderAccount)
                .where(
                    ProviderKey.user_id.in_(target_user_ids),
                    ProviderAccount.group_id.in_(group_ids)
                )
                .order_by(ProviderAccount.provider_id, ProviderKey.name)
            )
        else:
            # Fallback - no groups
            provider_keys_result = await db.execute(
                select(ProviderKey)
                .join(ProviderAccount)
                .where(
                    ProviderKey.user_id.in_(target_user_ids),
                    ProviderAccount.group_id.is_(None)
                )
                .order_by(ProviderAccount.provider_id, ProviderKey.name)
            )
    else:
        # No group context - get provider keys created by user that have no group association
        # This handles the case where user has personal keys not in any group
        provider_keys_result = await db.execute(
            select(ProviderKey)
            .join(ProviderAccount)
            .where(
                ProviderKey.user_id.in_(target_user_ids),
                ProviderAccount.group_id.is_(None)
            )
            .order_by(ProviderAccount.provider_id, ProviderKey.name)
        )
    all_provider_keys = provider_keys_result.scalars().all()

    # Get usage stats
    total_requests = 0
    total_tokens = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0
    total_input_cost = 0
    total_output_cost = 0
    avg_latency = 0
    usage_by_provider = {}
    usage_by_model = {}
    usage_by_api_key = {}
    usage_by_provider_key = {}
    usage_by_app = {}
    usage_by_group = {}
    usage_by_service = {}
    usage_by_team = {}
    daily_usage = []
    app_ids = []

    if api_key_ids:
        # Build base filter conditions
        base_conditions = [
            UsageLog.api_key_id.in_(api_key_ids),
            UsageLog.created_at >= period_start
        ]
        if filter_provider:
            base_conditions.append(UsageLog.provider == filter_provider)
        if filter_app_id:
            base_conditions.append(UsageLog.app_id == filter_app_id)
        if filter_provider_key_id:
            base_conditions.append(UsageLog.provider_key_id == filter_provider_key_id)
        if filter_service_id:
            base_conditions.append(UsageLog.service_id == filter_service_id)
        if filter_team_id:
            base_conditions.append(UsageLog.team_id_at_request == filter_team_id)

        # Get distinct app_ids for filter dropdown
        app_ids_result = await db.execute(
            select(UsageLog.app_id)
            .where(UsageLog.api_key_id.in_(api_key_ids))
            .where(UsageLog.app_id.isnot(None))
            .distinct()
        )
        app_ids = [row[0] for row in app_ids_result if row[0]]

        # Fetch all usage logs for the period to calculate costs dynamically
        # This allows us to use the pricing table for accurate historical cost calculation
        logs_result = await db.execute(
            select(UsageLog).where(*base_conditions)
        )
        all_logs = logs_result.scalars().all()

        # Calculate costs for each log and aggregate
        total_latency_sum = 0
        latency_count = 0

        # Aggregation dictionaries
        provider_agg = {}  # provider -> {requests, cost, tokens}
        model_agg = {}     # model -> {provider, requests, cost}
        api_key_agg = {}   # api_key_id -> {requests, cost, tokens}
        provider_key_agg = {}  # provider_key_id -> {provider, requests, cost, tokens}
        daily_agg = {}     # date_str -> {requests, cost, tokens}
        app_agg = {}       # app_id -> {requests, cost, tokens}
        group_agg = {}     # group_id -> {name, requests, cost, tokens}
        service_agg = {}   # service_id -> {name, requests, cost, tokens}
        team_agg = {}      # team_id -> {name, requests, cost, tokens}

        # Build service and team lookup tables
        service_lookup = {s.id: s.name for s in all_services}
        team_lookup = {t.id: t.name for t in all_teams}

        # Build API key to group mapping for group aggregation
        api_key_to_group = {}  # api_key_id -> {group_id, group_name}
        if platform_admin_mode:
            # Platform admin: get all groups for mapping
            all_groups_result = await db.execute(select(Group))
            all_groups_list = list(all_groups_result.scalars().all())
            group_lookup = {g.id: g.name for g in all_groups_list}
            for key in all_api_keys:
                if key.group_id and key.group_id in group_lookup:
                    api_key_to_group[key.id] = {
                        "group_id": key.group_id,
                        "group_name": group_lookup[key.group_id]
                    }
        elif all_groups_mode:
            group_lookup = {g.id: g.name for g in groups}
            for key in all_api_keys:
                if key.group_id and key.group_id in group_lookup:
                    api_key_to_group[key.id] = {
                        "group_id": key.group_id,
                        "group_name": group_lookup[key.group_id]
                    }

        for log in all_logs:
            # Get pricing and calculate costs
            pricing = await get_pricing_for_date(db, log.provider, log.model, log.created_at.date())
            usage_tokens = UsageTokens(
                input_tokens=log.input_tokens or 0,
                output_tokens=log.output_tokens or 0,
                cache_read_tokens=log.cache_read_tokens or 0,
                cache_write_tokens=log.cache_write_tokens or 0,
                reasoning_tokens=log.reasoning_tokens or 0,
                image_input_tokens=log.image_input_tokens or 0,
                audio_input_tokens=log.audio_input_tokens or 0,
                audio_output_tokens=log.audio_output_tokens or 0,
                video_input_tokens=log.video_input_tokens or 0,
                is_batch=log.is_batch or False,
                total_context_tokens=log.total_context_tokens,
            )
            input_cost_cents, output_cost_cents = calculate_input_output_costs(pricing, usage_tokens)
            cost_cents = input_cost_cents + output_cost_cents

            input_tokens = log.input_tokens or 0
            output_tokens = log.output_tokens or 0
            tokens = input_tokens + output_tokens

            # Total stats
            total_requests += 1
            total_tokens += tokens
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            total_cost += cost_cents / 100  # Convert to dollars
            total_input_cost += input_cost_cents / 100
            total_output_cost += output_cost_cents / 100
            if log.latency_ms:
                total_latency_sum += log.latency_ms
                latency_count += 1

            # By provider
            if log.provider not in provider_agg:
                provider_agg[log.provider] = {
                    "requests": 0, "cost": 0, "tokens": 0,
                    "input_tokens": 0, "output_tokens": 0,
                    "input_cost": 0, "output_cost": 0
                }
            provider_agg[log.provider]["requests"] += 1
            provider_agg[log.provider]["cost"] += cost_cents / 100
            provider_agg[log.provider]["tokens"] += tokens
            provider_agg[log.provider]["input_tokens"] += input_tokens
            provider_agg[log.provider]["output_tokens"] += output_tokens
            provider_agg[log.provider]["input_cost"] += input_cost_cents / 100
            provider_agg[log.provider]["output_cost"] += output_cost_cents / 100

            # By model
            if log.model not in model_agg:
                model_agg[log.model] = {"provider": log.provider, "requests": 0, "cost": 0}
            model_agg[log.model]["requests"] += 1
            model_agg[log.model]["cost"] += cost_cents / 100

            # By API key
            if log.api_key_id not in api_key_agg:
                api_key_agg[log.api_key_id] = {"requests": 0, "cost": 0, "tokens": 0}
            api_key_agg[log.api_key_id]["requests"] += 1
            api_key_agg[log.api_key_id]["cost"] += cost_cents / 100
            api_key_agg[log.api_key_id]["tokens"] += tokens

            # By provider key
            if log.provider_key_id:
                if log.provider_key_id not in provider_key_agg:
                    provider_key_agg[log.provider_key_id] = {
                        "provider": log.provider, "requests": 0, "cost": 0, "tokens": 0
                    }
                provider_key_agg[log.provider_key_id]["requests"] += 1
                provider_key_agg[log.provider_key_id]["cost"] += cost_cents / 100
                provider_key_agg[log.provider_key_id]["tokens"] += tokens

            # By date
            date_str = str(log.created_at.date())
            if date_str not in daily_agg:
                daily_agg[date_str] = {"requests": 0, "cost": 0, "tokens": 0}
            daily_agg[date_str]["requests"] += 1
            daily_agg[date_str]["cost"] += cost_cents / 100
            daily_agg[date_str]["tokens"] += tokens

            # By app_id (if set)
            if log.app_id:
                if log.app_id not in app_agg:
                    app_agg[log.app_id] = {
                        "requests": 0, "cost": 0, "tokens": 0,
                        "input_tokens": 0, "output_tokens": 0,
                        "input_cost": 0, "output_cost": 0
                    }
                app_agg[log.app_id]["requests"] += 1
                app_agg[log.app_id]["cost"] += cost_cents / 100
                app_agg[log.app_id]["tokens"] += tokens
                app_agg[log.app_id]["input_tokens"] += input_tokens
                app_agg[log.app_id]["output_tokens"] += output_tokens
                app_agg[log.app_id]["input_cost"] += input_cost_cents / 100
                app_agg[log.app_id]["output_cost"] += output_cost_cents / 100

            # By group (in all_groups_mode or platform_admin_mode)
            if (all_groups_mode or platform_admin_mode) and log.api_key_id in api_key_to_group:
                group_info = api_key_to_group[log.api_key_id]
                gid = group_info["group_id"]
                if gid not in group_agg:
                    group_agg[gid] = {
                        "name": group_info["group_name"],
                        "requests": 0, "cost": 0, "tokens": 0
                    }
                group_agg[gid]["requests"] += 1
                group_agg[gid]["cost"] += cost_cents / 100
                group_agg[gid]["tokens"] += tokens

            # By service (if service_id is populated)
            if log.service_id:
                sid = log.service_id
                if sid not in service_agg:
                    service_agg[sid] = {
                        "name": service_lookup.get(sid, f"Service {sid[:8]}..."),
                        "requests": 0, "cost": 0, "tokens": 0
                    }
                service_agg[sid]["requests"] += 1
                service_agg[sid]["cost"] += cost_cents / 100
                service_agg[sid]["tokens"] += tokens

            # By team (if team_id_at_request is populated)
            if log.team_id_at_request:
                tid = log.team_id_at_request
                if tid not in team_agg:
                    team_agg[tid] = {
                        "name": team_lookup.get(tid, f"Team {tid[:8]}..."),
                        "requests": 0, "cost": 0, "tokens": 0
                    }
                team_agg[tid]["requests"] += 1
                team_agg[tid]["cost"] += cost_cents / 100
                team_agg[tid]["tokens"] += tokens

        # Calculate average latency
        avg_latency = int(total_latency_sum / latency_count) if latency_count > 0 else 0

        # Convert aggregations to expected format
        usage_by_provider = provider_agg

        # Top 10 models by requests
        model_sorted = sorted(model_agg.items(), key=lambda x: x[1]["requests"], reverse=True)[:10]
        usage_by_model = {k: v for k, v in model_sorted}

        # API key usage with names
        api_key_lookup = {k.id: k for k in all_api_keys}
        for key_id, data in api_key_agg.items():
            key = api_key_lookup.get(key_id)
            usage_by_api_key[key_id] = {
                "name": key.name if key else "Unknown",
                **data
            }

        # Provider key usage with names
        provider_key_lookup = {pk.id: pk for pk in all_provider_keys}
        for pk_id, data in provider_key_agg.items():
            pk = provider_key_lookup.get(pk_id)
            usage_by_provider_key[pk_id] = {
                "name": pk.name if pk else "Unknown",
                **data
            }

        # Daily usage sorted by date
        daily_usage = [
            {"date": date_str, **data}
            for date_str, data in sorted(daily_agg.items())
        ]

        # App usage sorted by cost descending
        usage_by_app = dict(sorted(app_agg.items(), key=lambda x: x[1]["cost"], reverse=True))

        # Group usage sorted by cost descending (in all_groups_mode or platform_admin_mode)
        if all_groups_mode or platform_admin_mode:
            usage_by_group = dict(sorted(group_agg.items(), key=lambda x: x[1]["cost"], reverse=True))

        # Service usage sorted by cost descending
        usage_by_service = dict(sorted(service_agg.items(), key=lambda x: x[1]["cost"], reverse=True))

        # Team usage sorted by cost descending
        usage_by_team = dict(sorted(team_agg.items(), key=lambda x: x[1]["cost"], reverse=True))

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "active_org": active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost": total_cost,
            "total_input_cost": total_input_cost,
            "total_output_cost": total_output_cost,
            "avg_latency": avg_latency,
            "usage_by_provider": usage_by_provider,
            "usage_by_model": usage_by_model,
            "usage_by_api_key": usage_by_api_key,
            "usage_by_provider_key": usage_by_provider_key,
            "usage_by_app": usage_by_app,
            "daily_usage": daily_usage,
            "app_ids": app_ids,
            "all_api_keys": all_api_keys,
            "all_provider_keys": all_provider_keys,
            "group_users": group_users,
            "filter_provider": filter_provider,
            "filter_app_id": filter_app_id,
            "filter_key_id": filter_key_id,
            "filter_provider_key_id": filter_provider_key_id,
            "filter_user_id": filter_user_id,
            "filter_period": filter_period,
            "filter_service_id": filter_service_id,
            "filter_team_id": filter_team_id,
            "usage_by_group": usage_by_group,
            "usage_by_service": usage_by_service,
            "usage_by_team": usage_by_team,
            "all_services": all_services,
            "all_teams": all_teams,
            "all_groups_mode": all_groups_mode,
            "is_platform_admin": is_platform_admin,
            "platform_admin_mode": platform_admin_mode,
        },
    )


@router.get("/api/model-pricing/{provider}/{model:path}")
async def get_model_pricing(
    provider: str,
    model: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get pricing information for a specific model.
    Uses synced data from ProviderModel table (from OpenRouter API sync).
    Returns 404 if model not found - no fallback pricing.
    """
    from app.models import ProviderModel

    # Look up model from synced data
    result = await db.execute(
        select(ProviderModel).where(
            ProviderModel.provider_id == provider,
            ProviderModel.model_id == model,
        )
    )
    provider_model = result.scalar_one_or_none()

    if not provider_model:
        raise HTTPException(
            status_code=404,
            detail=f"Pricing not found for {provider}/{model}. Try syncing models."
        )

    # Format prices for display (convert cents per 1M to dollars per 1M)
    def format_price(cents_per_1m: float | None) -> str:
        if cents_per_1m is None:
            return "N/A"
        if cents_per_1m == 0:
            return "Free"
        elif cents_per_1m < 100:
            return f"${cents_per_1m / 100:.4f}"
        else:
            return f"${cents_per_1m / 100:.2f}"

    # Build response from synced model data
    response = {
        "provider": provider,
        "model": model,
        "name": provider_model.name,
        "description": provider_model.description,
        "context_length": provider_model.context_length,
        "max_completion_tokens": provider_model.max_completion_tokens,
        "last_synced": provider_model.last_synced_at.isoformat() if provider_model.last_synced_at else None,
        "pricing": {},
        "features": {},
    }

    # Add input/output pricing if available
    if provider_model.input_price_per_1m is not None:
        response["pricing"]["input"] = {
            "price_per_1m_tokens": format_price(provider_model.input_price_per_1m),
            "raw_cents": provider_model.input_price_per_1m,
        }
    if provider_model.output_price_per_1m is not None:
        response["pricing"]["output"] = {
            "price_per_1m_tokens": format_price(provider_model.output_price_per_1m),
            "raw_cents": provider_model.output_price_per_1m,
        }

    # Extract additional pricing from raw_data (OpenRouter response)
    raw_data = provider_model.raw_data or {}
    raw_pricing = raw_data.get("pricing", {})

    # Image pricing (dollars per image - flat fee per image, not per token)
    if raw_pricing.get("image"):
        try:
            image_price = float(raw_pricing["image"])
            if image_price > 0:
                response["pricing"]["image"] = {
                    "per_image": f"${image_price:.4f}",
                    "raw_dollars": image_price,
                }
                response["features"]["vision"] = True
        except (ValueError, TypeError):
            pass

    # Request cost (flat fee per request)
    if raw_pricing.get("request"):
        try:
            request_price = float(raw_pricing["request"])
            if request_price > 0:
                response["pricing"]["request"] = {
                    "per_request": f"${request_price:.6f}",
                    "raw_dollars": request_price,
                }
        except (ValueError, TypeError):
            pass

    # Web search pricing
    if raw_pricing.get("web_search"):
        try:
            web_search_price = float(raw_pricing["web_search"])
            if web_search_price > 0:
                response["pricing"]["web_search"] = {
                    "per_search": f"${web_search_price:.4f}",
                    "raw_dollars": web_search_price,
                }
                response["features"]["web_search"] = True
        except (ValueError, TypeError):
            pass

    # Internal reasoning pricing
    if raw_pricing.get("internal_reasoning"):
        try:
            reasoning_price = float(raw_pricing["internal_reasoning"])
            if reasoning_price > 0:
                reasoning_cents_per_1m = reasoning_price * 1_000_000 * 100
                response["pricing"]["reasoning"] = {
                    "price_per_1m_tokens": format_price(reasoning_cents_per_1m),
                    "raw_cents": reasoning_cents_per_1m,
                }
                response["features"]["reasoning_tokens"] = True
        except (ValueError, TypeError):
            pass

    # Extract architecture/modality info
    architecture = provider_model.architecture or raw_data.get("architecture", {})
    if architecture:
        modality = architecture.get("modality", "")
        if "image" in modality:
            response["features"]["vision"] = True
        if "audio" in modality:
            response["features"]["audio"] = True
        response["modality"] = modality

        input_modalities = architecture.get("input_modalities", [])
        output_modalities = architecture.get("output_modalities", [])
        if input_modalities:
            response["input_modalities"] = input_modalities
        if output_modalities:
            response["output_modalities"] = output_modalities

    return response
