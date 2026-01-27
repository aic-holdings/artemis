import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Float, Text, JSON, UniqueConstraint, Boolean, Date, TIMESTAMP
from sqlalchemy.orm import relationship

from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


def utc_now():
    return datetime.now(timezone.utc)


class Organization(Base):
    """Organizations group users and can share resources."""
    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, unique=True, index=True)
    owner_id = Column(String, ForeignKey("users.id", use_alter=True, name="fk_org_owner"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_organizations")
    users = relationship("User", foreign_keys="User.organization_id", back_populates="organization")
    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    groups = relationship("Group", back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    supabase_id = Column(String, unique=True, nullable=True, index=True)  # Stable ID from Jetta SSO
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    tier = Column(String, default="free")  # free, pro, enterprise
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    settings = Column(JSON, nullable=True, default=dict)  # User preferences (last_org_id, theme, etc.)
    is_service_account = Column(Boolean, default=False, nullable=False)  # Machine identity for apps
    is_platform_admin = Column(Boolean, default=False, nullable=False)  # Can see ALL orgs/usage (AIC Holdings admins)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    organization = relationship("Organization", foreign_keys=[organization_id], back_populates="users")
    owned_organizations = relationship("Organization", foreign_keys="Organization.owner_id", back_populates="owner")
    org_memberships = relationship("OrganizationMember", foreign_keys="OrganizationMember.user_id", back_populates="user", cascade="all, delete-orphan")
    group_memberships = relationship("GroupMember", foreign_keys="GroupMember.user_id", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    provider_keys = relationship("ProviderKey", back_populates="user", cascade="all, delete-orphan")

    def get_setting(self, key: str, default=None):
        """Get a user setting by key."""
        if not self.settings:
            return default
        return self.settings.get(key, default)

    def set_setting(self, key: str, value):
        """Set a user setting. Must call db.commit() after.

        Note: This creates a new dict to ensure SQLAlchemy detects the change.
        """
        if not self.settings:
            self.settings = {key: value}
        else:
            # Create new dict to trigger SQLAlchemy change detection
            self.settings = {**self.settings, key: value}


class OrganizationMember(Base):
    """Organization membership with role and invite status."""
    __tablename__ = "organization_members"

    id = Column(String, primary_key=True, default=generate_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)  # Null for pending invites
    email = Column(String, nullable=False, index=True)  # Email for invite tracking
    role = Column(String, nullable=False, default="member")  # owner, admin, member
    status = Column(String, nullable=False, default="pending")  # pending, active, revoked
    invited_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    invited_at = Column(DateTime(timezone=True), default=utc_now)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization", back_populates="members")
    user = relationship("User", foreign_keys=[user_id], back_populates="org_memberships")
    invited_by = relationship("User", foreign_keys=[invited_by_id])

    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="unique_org_member_email"),
    )


class Group(Base):
    """Groups within organizations for organizing keys and access."""
    __tablename__ = "groups"

    id = Column(String, primary_key=True, default=generate_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)  # Default group for new org members
    created_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    organization = relationship("Organization", back_populates="groups")
    created_by = relationship("User", foreign_keys=[created_by_id])
    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="group", cascade="all, delete-orphan")
    provider_accounts = relationship("ProviderAccount", back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="unique_org_group_name"),
    )


class GroupMember(Base):
    """User membership in a group with role."""
    __tablename__ = "group_members"

    id = Column(String, primary_key=True, default=generate_uuid)
    group_id = Column(String, ForeignKey("groups.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False, default="member")  # admin, member, viewer
    added_at = Column(DateTime(timezone=True), default=utc_now)
    added_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    group = relationship("Group", back_populates="members")
    user = relationship("User", foreign_keys=[user_id], back_populates="group_memberships")
    added_by = relationship("User", foreign_keys=[added_by_id])

    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="unique_group_member"),
    )


# ===========================================
# NEW DATA MODEL: Teams & Services
# ===========================================
# Teams: Groups of people (users)
# Services: Applications that call LLMs (have API keys)
# This separates "who uses" from "what uses" for cleaner analytics


class Team(Base):
    """
    Teams are groups of people within an organization.

    Teams own Services. A user can belong to multiple teams.
    Analytics can be sliced by team via denormalized team_id on UsageLog.
    """
    __tablename__ = "teams"

    id = Column(String, primary_key=True, default=generate_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="active")  # active, archived
    created_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete

    organization = relationship("Organization", backref="teams")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    members = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    services = relationship("Service", back_populates="team")

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="unique_org_team_name"),
    )


class TeamMember(Base):
    """
    Pivot table for users belonging to teams.

    Users can belong to multiple teams within an organization.
    """
    __tablename__ = "team_members"

    id = Column(String, primary_key=True, default=generate_uuid)
    team_id = Column(String, ForeignKey("teams.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False, default="member")  # admin, member
    added_at = Column(DateTime(timezone=True), default=utc_now)
    added_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)

    team = relationship("Team", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
    added_by = relationship("User", foreign_keys=[added_by_user_id])

    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="unique_team_member"),
    )


class Service(Base):
    """
    Services are applications that call LLMs through Artemis.

    Examples: forge, taskr, watts, customer-facing-app

    Services:
    - Belong to an organization
    - Optionally belong to a team (for ownership/billing)
    - Have API keys issued to them
    - Can be suspended (immediately revokes all keys)
    - Can have spending alerts and budgets
    """
    __tablename__ = "services"

    id = Column(String, primary_key=True, default=generate_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    team_id = Column(String, ForeignKey("teams.id"), nullable=True, index=True)  # Owning team
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # Status
    status = Column(String, nullable=False, default="active")  # active, suspended
    suspended_at = Column(DateTime(timezone=True), nullable=True)
    suspended_reason = Column(Text, nullable=True)
    suspended_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)

    # Spending controls
    alert_threshold_cents = Column(Integer, nullable=True)  # Rolling 24h spend alert
    monthly_budget_cents = Column(Integer, nullable=True)   # Optional hard/soft cap

    # Audit
    created_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete

    organization = relationship("Organization", backref="services")
    team = relationship("Team", back_populates="services")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    suspended_by = relationship("User", foreign_keys=[suspended_by_user_id])
    api_keys = relationship("APIKey", back_populates="service")

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="unique_org_service_name"),
    )


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=generate_uuid)
    group_id = Column(String, ForeignKey("groups.id"), nullable=True, index=True)  # Keys belong to groups (LEGACY)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)  # Created by user (audit trail)
    key_hash = Column(String, nullable=False)
    key_prefix = Column(String, nullable=False)  # First 8 chars for display
    encrypted_key = Column(Text, nullable=True)  # Encrypted full key for reveal
    name = Column(String, default="Default")
    is_default = Column(Boolean, default=False)  # Default key for chat/testing
    is_system = Column(Boolean, default=False, nullable=False)  # System keys (e.g., Artemis-Test) cannot be edited
    created_at = Column(DateTime(timezone=True), default=utc_now)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    # Override which provider key to use per provider (e.g., {"openai": "uuid-of-key"})
    provider_key_overrides = Column(JSON, nullable=True)

    # NEW: Service-based key management
    service_id = Column(String, ForeignKey("services.id"), nullable=True, index=True)  # Service this key belongs to
    environment = Column(String, nullable=True)  # prod, staging, dev
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Key expiration
    rotation_group_id = Column(String, nullable=True, index=True)  # Links keys from same rotation cycle

    group = relationship("Group", back_populates="api_keys")
    user = relationship("User", back_populates="api_keys")
    service = relationship("Service", back_populates="api_keys")
    usage_logs = relationship("UsageLog", back_populates="api_key", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("group_id", "name", name="unique_group_key_name"),
    )


class Provider(Base):
    """
    Supported LLM providers.

    This is a reference table for provider metadata. The provider 'slug' (e.g., 'openai')
    is used as the identifier throughout the system.
    """
    __tablename__ = "providers"

    id = Column(String, primary_key=True)  # slug: openai, anthropic, google, perplexity, openrouter
    name = Column(String, nullable=False)  # Display name: OpenAI, Anthropic, etc.
    base_url = Column(String, nullable=True)  # Base API URL
    docs_url = Column(String, nullable=True)  # Link to provider API docs
    is_active = Column(Boolean, default=True, nullable=False)  # Enable/disable provider
    created_at = Column(DateTime(timezone=True), default=utc_now)

    accounts = relationship("ProviderAccount", back_populates="provider")
    models = relationship("ProviderModel", back_populates="provider", cascade="all, delete-orphan")


class ProviderModel(Base):
    """
    Available models for a provider.

    Models can be fetched from provider APIs (like OpenRouter) and users
    can enable/disable which models they want to expose in their Artemis instance.
    """
    __tablename__ = "provider_models"

    id = Column(String, primary_key=True, default=generate_uuid)
    provider_id = Column(String, ForeignKey("providers.id"), nullable=False, index=True)
    model_id = Column(String, nullable=False, index=True)  # API model ID: gpt-4o, claude-3-5-sonnet, etc.
    name = Column(String, nullable=False)  # Display name from provider
    description = Column(Text, nullable=True)

    # Capabilities
    context_length = Column(Integer, nullable=True)
    max_completion_tokens = Column(Integer, nullable=True)

    # Pricing (cents per 1M tokens, from provider API)
    input_price_per_1m = Column(Float, nullable=True)
    output_price_per_1m = Column(Float, nullable=True)

    # User control
    is_enabled = Column(Boolean, default=True, nullable=False)  # User can disable models

    # Metadata
    architecture = Column(JSON, nullable=True)  # Modalities, tokenizer info, etc.
    raw_data = Column(JSON, nullable=True)  # Full response from provider API for reference
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    provider = relationship("Provider", back_populates="models")

    __table_args__ = (
        UniqueConstraint("provider_id", "model_id", name="unique_provider_model"),
    )


class ProviderAccount(Base):
    """
    An account with a provider (e.g., an OpenAI organization account).

    Groups can have multiple accounts per provider, and each account can have
    multiple API keys. This allows tracking billing, rate limits, and usage
    at the account level.
    """
    __tablename__ = "provider_accounts"

    id = Column(String, primary_key=True, default=generate_uuid)
    group_id = Column(String, ForeignKey("groups.id"), nullable=False, index=True)
    provider_id = Column(String, ForeignKey("providers.id"), nullable=False, index=True)
    name = Column(String, nullable=False)  # "Engineering Account", "Research Account"

    # Account identification
    external_account_id = Column(String, nullable=True)  # Provider's account/org ID if available
    account_email = Column(String, nullable=True)  # Primary email for the account
    billing_email = Column(String, nullable=True)  # Billing contact email
    account_phone = Column(String, nullable=True)  # Contact phone

    # Metadata
    notes = Column(Text, nullable=True)  # Additional info about the account
    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    group = relationship("Group", back_populates="provider_accounts")
    provider = relationship("Provider", back_populates="accounts")
    created_by = relationship("User", foreign_keys=[created_by_id])
    keys = relationship("ProviderKey", back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("group_id", "provider_id", "name", name="unique_group_provider_account_name"),
    )


class ProviderKey(Base):
    """
    An API key for a provider account.

    Keys belong to accounts, which belong to groups. A key can optionally be marked
    as the default for its provider within the group.
    """
    __tablename__ = "provider_keys"

    id = Column(String, primary_key=True, default=generate_uuid)
    provider_account_id = Column(String, ForeignKey("provider_accounts.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)  # Created by user (audit trail)
    encrypted_key = Column(Text, nullable=False)
    name = Column(String, nullable=False)  # Key name: "Production Key", "Dev Key"
    key_suffix = Column(String, nullable=True)  # Last 4 chars for identification
    is_default = Column(Boolean, default=False, nullable=False)  # Default key for this provider in group
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    account = relationship("ProviderAccount", back_populates="keys")
    user = relationship("User", back_populates="provider_keys")
    usage_logs = relationship("UsageLog", back_populates="provider_key")

    __table_args__ = (
        UniqueConstraint("provider_account_id", "name", name="unique_account_key_name"),
    )


class UsageLog(Base):
    """
    Tracks individual API request usage with detailed token breakdowns.

    Token types follow the union of what major providers report:
    - OpenAI: input, output, cached_input, reasoning (o1/o3 models)
    - Anthropic: input, output, cache_read, cache_creation (prompt caching)
    - Google: input, output, cached (context caching), multimodal tokens

    Cost is calculated on-the-fly from ModelPricing table using the request's
    created_at date to find applicable pricing.
    """
    __tablename__ = "usage_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    api_key_id = Column(String, ForeignKey("api_keys.id"), nullable=False)
    provider_key_id = Column(String, ForeignKey("provider_keys.id"), nullable=True, index=True)
    provider = Column(String, nullable=False, index=True)
    model = Column(String, nullable=False, index=True)

    # ===========================================
    # Denormalized Snapshots (for stable analytics)
    # ===========================================
    # These capture the state AT REQUEST TIME and don't change if relationships change later.
    # This ensures historical analytics remain accurate even if a service moves to a different team.
    service_id = Column(String, nullable=True, index=True)              # Service that made this request
    team_id_at_request = Column(String, nullable=True, index=True)      # Team owning service at request time
    api_key_created_by_user_id = Column(String, nullable=True, index=True)  # Who created the API key

    # ===========================================
    # Core Token Counts (all providers)
    # ===========================================
    input_tokens = Column(Integer, default=0)       # Standard input/prompt tokens
    output_tokens = Column(Integer, default=0)      # Standard output/completion tokens

    # ===========================================
    # Caching Token Counts
    # ===========================================
    # Cache READ tokens - heavily discounted (10-25% of input price)
    # OpenAI: cached_tokens, Anthropic: cache_read, Google: cached_content
    cache_read_tokens = Column(Integer, default=0)

    # Cache WRITE tokens - may have premium (Anthropic: 1.25x-2x depending on TTL)
    # Only Anthropic currently charges separately for cache writes
    cache_write_tokens = Column(Integer, default=0)

    # ===========================================
    # Reasoning/Thinking Tokens
    # ===========================================
    # Internal reasoning tokens (OpenAI o1/o3, Anthropic extended thinking)
    # These are typically charged at output rates or have dedicated pricing
    reasoning_tokens = Column(Integer, default=0)

    # ===========================================
    # Multimodal Token Counts
    # ===========================================
    image_input_tokens = Column(Integer, default=0)   # Image analysis input
    audio_input_tokens = Column(Integer, default=0)   # Speech-to-text input
    audio_output_tokens = Column(Integer, default=0)  # Text-to-speech output
    video_input_tokens = Column(Integer, default=0)   # Video analysis (Gemini)

    # ===========================================
    # Request Characteristics (affect pricing)
    # ===========================================
    # Whether this was a batch API request (typically 50% discount)
    is_batch = Column(Boolean, default=False, nullable=False)

    # Total context size - used for long-context pricing tiers
    # (e.g., Gemini Pro 2x pricing over 200K tokens)
    total_context_tokens = Column(Integer, nullable=True)

    # ===========================================
    # Performance & Metadata
    # ===========================================
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)

    # Tracking fields for filtering
    app_id = Column(String, nullable=True, index=True)
    end_user_id = Column(String, nullable=True, index=True)

    # Flexible metadata for provider-specific fields we don't have columns for
    request_metadata = Column(JSON, nullable=True)

    # ===========================================
    # Legacy field - DO NOT USE for new code
    # ===========================================
    # Cost should be calculated from ModelPricing table
    cost_cents = Column(Integer, default=0)

    api_key = relationship("APIKey", back_populates="usage_logs")
    provider_key = relationship("ProviderKey", back_populates="usage_logs")


class RequestLog(Base):
    """
    Structured logs for proxy requests - tracks request lifecycle, errors, and retries.

    This is separate from UsageLog which tracks token usage/costs.
    RequestLog captures operational data for debugging and health monitoring.
    """
    __tablename__ = "request_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    request_id = Column(String, nullable=False, index=True)  # Correlation ID across retries
    api_key_id = Column(String, ForeignKey("api_keys.id"), nullable=True, index=True)
    provider = Column(String, nullable=False, index=True)
    model = Column(String, nullable=True)

    # Request details
    endpoint = Column(String, nullable=False)  # e.g., "/v1/chat/completions"
    method = Column(String, nullable=False, default="POST")
    is_streaming = Column(Boolean, default=False)

    # Response details
    status_code = Column(Integer, nullable=True)
    error_type = Column(String, nullable=True, index=True)  # timeout, connection_error, http_error, etc.
    error_message = Column(Text, nullable=True)

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    latency_ms = Column(Integer, nullable=True)

    # Retry tracking
    attempt_number = Column(Integer, default=1)
    was_retried = Column(Boolean, default=False)

    # Context
    app_id = Column(String, nullable=True, index=True)
    client_ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)

    # Full request/response metadata for debugging
    request_metadata = Column(JSON, nullable=True)
    response_metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)


class AppLog(Base):
    """
    Application-level logs for frontend and backend events.

    Used to track errors, events, and debug info from both client-side
    JavaScript and server-side Python code with auto-timestamps.
    """
    __tablename__ = "app_logs"

    id = Column(String, primary_key=True, default=generate_uuid)

    # Source identification
    source = Column(String, nullable=False, index=True)  # "frontend", "backend"
    level = Column(String, nullable=False, index=True)   # "error", "warn", "info", "debug"

    # Error/event details
    message = Column(Text, nullable=False)
    error_type = Column(String, nullable=True, index=True)  # JS: "TypeError", Python: "ValueError"
    stack_trace = Column(Text, nullable=True)

    # Context
    page = Column(String, nullable=True, index=True)  # URL path: "/chat", "/dashboard"
    component = Column(String, nullable=True)         # Component/function name
    user_agent = Column(String, nullable=True)

    # Extra data for debugging
    extra_data = Column(JSON, nullable=True)  # Any additional context data

    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)


class ProviderHealthRecord(Base):
    """
    Stores provider health events for persistence across restarts.

    Each record represents a single request outcome (success/failure) for a provider.
    Used to reconstruct health metrics when the server starts.
    """
    __tablename__ = "provider_health_records"

    id = Column(String, primary_key=True, default=generate_uuid)
    provider = Column(String, nullable=False, index=True)
    is_success = Column(Boolean, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    error_type = Column(String, nullable=True, index=True)  # timeout, connection_error, http_error, etc.
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)


class ModelPricing(Base):
    """
    Historical pricing for models. Prices are stored per 1M tokens in CENTS.

    Design principles:
    1. Prices are per 1M tokens in cents (e.g., $3/1M = 300 cents)
    2. effective_date determines when pricing takes effect
    3. Most recent pricing on or before a date is used for calculation
    4. NULL means "not applicable to this model" (vs 0 = free)
    5. Multipliers (cache_read_multiplier, batch_discount) allow percentage-based pricing

    Pricing lookup:
    - Query by (provider, model, effective_date <= target_date)
    - Order by effective_date DESC, take first result
    - Fall back to static FALLBACK_PRICING if no DB match
    """
    __tablename__ = "model_pricing"

    id = Column(String, primary_key=True, default=generate_uuid)
    provider = Column(String, nullable=False, index=True)
    model = Column(String, nullable=False, index=True)  # Can include wildcards like "gpt-4o-*"
    effective_date = Column(Date, nullable=False, index=True)

    # ===========================================
    # Core Token Pricing (cents per 1M tokens)
    # ===========================================
    input_price_per_1m = Column(Float, nullable=False, default=0)
    output_price_per_1m = Column(Float, nullable=False, default=0)

    # ===========================================
    # Cache Pricing
    # ===========================================
    # Cache read: Usually a multiplier of input price (0.1 = 10% = 90% discount)
    # OpenAI: 50% discount, Anthropic: 90% discount, Google: 75-90% discount
    cache_read_multiplier = Column(Float, nullable=True)  # Multiplier of input_price (e.g., 0.1, 0.25, 0.5)

    # Cache write: Anthropic charges premium for cache writes
    # 5-min cache = 1.25x, 1-hour cache = 2.0x input price
    # NULL = no separate charge (write charged as regular input)
    cache_write_multiplier = Column(Float, nullable=True)  # Multiplier of input_price (e.g., 1.25, 2.0)

    # ===========================================
    # Reasoning/Thinking Tokens
    # ===========================================
    # OpenAI o1/o3: reasoning tokens charged at output rate
    # Anthropic: extended thinking has separate pricing
    # NULL = use output_price_per_1m
    reasoning_price_per_1m = Column(Float, nullable=True)

    # ===========================================
    # Multimodal Pricing (cents per 1M tokens)
    # ===========================================
    image_input_price_per_1m = Column(Float, nullable=True)
    audio_input_price_per_1m = Column(Float, nullable=True)
    audio_output_price_per_1m = Column(Float, nullable=True)
    video_input_price_per_1m = Column(Float, nullable=True)

    # ===========================================
    # Pricing Modifiers & Tiers
    # ===========================================
    # Batch API discount (0.5 = 50% of standard price)
    batch_discount = Column(Float, nullable=True, default=0.5)

    # Long context pricing tier threshold and multiplier
    # e.g., Gemini Pro charges 2x when context > 200K tokens
    long_context_threshold = Column(Integer, nullable=True)  # Token count threshold
    long_context_multiplier = Column(Float, nullable=True)   # e.g., 2.0 for double price

    # ===========================================
    # Fixed Costs
    # ===========================================
    # Per-request fee (rare, but some models have it)
    base_request_cost_cents = Column(Float, nullable=True, default=0)

    # ===========================================
    # Metadata
    # ===========================================
    created_at = Column(DateTime(timezone=True), default=utc_now)
    notes = Column(Text, nullable=True)  # Price change reasons, source URL, etc.

    __table_args__ = (
        UniqueConstraint("provider", "model", "effective_date", name="unique_model_pricing_date"),
    )
