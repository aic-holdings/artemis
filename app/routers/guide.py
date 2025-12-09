"""
Setup guide routes.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import APIKey
from app.routers.auth_routes import get_current_user, get_user_organizations, get_user_groups
from app.services.api_key_service import APIKeyService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/guide")
async def guide_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Setup guide page with copyable instructions."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)

    # Get user's first API key for the docs
    api_keys_result = await db.execute(
        select(APIKey).where(APIKey.user_id == user.id, APIKey.revoked_at.is_(None)).limit(1)
    )
    api_key = api_keys_result.scalar_one_or_none()

    # Determine base URL from request
    host = request.headers.get("host", "localhost:8000")
    scheme = "https" if not host.startswith("localhost") and not host.startswith("127.") else "http"
    base_url = f"{scheme}://{host}"

    groups = await get_user_groups(user.id, ctx.active_org_id, db) if ctx.active_org_id else []

    # Track if we're in "All Groups" mode (org selected but no specific group)
    all_groups_mode = ctx.active_org_id and not ctx.active_group_id

    return templates.TemplateResponse(
        request,
        "guide.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "base_url": base_url,
            "artemis_key": api_key.key_prefix + "..." if api_key else None,
            "all_groups_mode": all_groups_mode,
        },
    )


@router.get("/agent-guide")
async def agent_guide_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    key_id: str = None,
):
    """AI Agent configuration guide with full API key and machine-readable instructions."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    user = ctx.user
    organizations = await get_user_organizations(user.id, db)
    api_key_service = APIKeyService(db)

    # Get API keys - filter by active group when selected
    api_keys = []
    keys_by_group = {}  # {group_name: [keys]}

    if ctx.active_group_id:
        # When a specific group is selected, only show keys from that group
        group_keys = await api_key_service.get_all_for_group(ctx.active_group_id)
        group_keys = [k for k in group_keys if k.revoked_at is None and not k.is_system]
        if group_keys:
            keys_by_group[ctx.active_group.name] = group_keys
            api_keys = group_keys
    elif ctx.active_org_id:
        # When org is selected but no specific group, show keys from all groups user belongs to
        all_groups = await get_user_groups(user.id, ctx.active_org_id, db)
        for group in all_groups:
            group_keys = await api_key_service.get_all_for_group(group.id)
            group_keys = [k for k in group_keys if k.revoked_at is None and not k.is_system]
            if group_keys:
                keys_by_group[group.name] = group_keys
                api_keys.extend(group_keys)
    else:
        # Personal keys (no org/group)
        personal_keys = await api_key_service.get_all_for_user(user.id, group_id=None)
        personal_keys = [k for k in personal_keys if k.revoked_at is None and not k.is_system]
        if personal_keys:
            keys_by_group["Personal"] = personal_keys
            api_keys = personal_keys

    # Determine base URL from request
    host = request.headers.get("host", "localhost:8000")
    scheme = "https" if not host.startswith("localhost") and not host.startswith("127.") else "http"
    base_url = f"{scheme}://{host}"

    # Get selected key and reveal it
    selected_key = None
    revealed_key = None

    if key_id:
        # Verify key belongs to user (from any group they have access to)
        selected_key = await api_key_service.get_by_id(key_id, user_id=user.id)
        if selected_key and selected_key.is_system:
            selected_key = None  # Don't allow system keys
        # Verify the key is in our allowed list
        if selected_key and selected_key not in api_keys:
            selected_key = None
        if selected_key and selected_key.encrypted_key:
            revealed_key = await api_key_service.reveal(key_id, user.id)
    elif api_keys:
        # Auto-select first key (already filtered to non-system keys)
        selected_key = api_keys[0]
        if selected_key.encrypted_key:
            revealed_key = await api_key_service.reveal(selected_key.id, user.id)

    groups = await get_user_groups(user.id, ctx.active_org_id, db) if ctx.active_org_id else []

    # Track if we're in "All Groups" mode (org selected but no specific group)
    all_groups_mode = ctx.active_org_id and not ctx.active_group_id

    return templates.TemplateResponse(
        request,
        "agent_guide.html",
        {
            "user": user,
            "active_org": ctx.active_org,
            "active_group": ctx.active_group,
            "organizations": organizations,
            "groups": groups,
            "base_url": base_url,
            "api_keys": api_keys,
            "keys_by_group": keys_by_group,
            "selected_key": selected_key,
            "revealed_key": revealed_key,
            "all_groups_mode": all_groups_mode,
        },
    )


@router.get("/downloads/artemis_client.py")
async def download_python_client(request: Request, db: AsyncSession = Depends(get_db)):
    """Download the Artemis Python client helper module."""
    ctx = await get_current_user(request, db)
    if not ctx:
        return RedirectResponse(url="/login", status_code=303)

    # Determine base URL from request
    host = request.headers.get("host", "localhost:8000")
    scheme = "https" if not host.startswith("localhost") and not host.startswith("127.") else "http"
    base_url = f"{scheme}://{host}"

    client_code = f'''"""
Artemis LLM Proxy Client
========================

WHAT IS ARTEMIS?
----------------
Artemis is a unified LLM proxy server that sits between your application and
LLM providers (OpenAI, Anthropic, OpenRouter, Perplexity, Google).

HOW IT WORKS:
1. Your app makes a request to Artemis (not directly to OpenAI/Anthropic)
2. Artemis validates your Artemis API key (art_xxx)
3. Artemis looks up the real provider API key from its secure database
4. Artemis forwards your request to the actual provider
5. Artemis logs the request for usage tracking
6. Artemis returns the provider's response to your app

IMPORTANT - YOU ONLY NEED ONE API KEY:
- Use your Artemis API key (starts with 'art_') for ALL providers
- You do NOT need OpenAI/Anthropic API keys
- Artemis handles all provider authentication internally

Installation:
    pip install openai anthropic

Basic Usage:
    from artemis_client import ArtemisClient

    client = ArtemisClient()
    response = client.openai.chat.completions.create(
        model="gpt-4o",
        messages=[{{"role": "user", "content": "Hello!"}}]
    )

Using OpenAI SDK directly (without this helper):
    from openai import OpenAI
    import os

    # Point base_url to Artemis, NOT api.openai.com
    client = OpenAI(
        base_url="{base_url}/v1/openai",
        api_key=os.getenv("ARTEMIS_API_KEY")  # Your Artemis key, NOT OpenAI
    )

Environment Variables:
    ARTEMIS_API_KEY - Your Artemis API key (required)
    ARTEMIS_BASE_URL - Artemis server URL (default: {base_url})
"""

import os
from typing import Optional


class ArtemisClient:
    """
    Unified client for accessing LLM providers through Artemis proxy.

    This client automatically configures OpenAI and Anthropic SDKs to route
    all requests through Artemis. You ONLY need your Artemis API key (art_xxx) -
    Artemis handles all provider authentication internally.

    Request Flow:
        Your App -> ArtemisClient -> Artemis Server -> Provider (OpenAI/Anthropic/etc)

    Supported Providers:
        - openai: GPT-4o, GPT-4, GPT-3.5-turbo, etc.
        - anthropic: Claude 3.5 Sonnet, Claude 3 Opus, etc.
        - openrouter: Access to 100+ models from various providers
        - perplexity: Sonar models with internet search
    """

    # Default configuration - update these for your deployment
    DEFAULT_BASE_URL = "{base_url}"
    DEFAULT_API_KEY = os.getenv("ARTEMIS_API_KEY", "")

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        app_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """
        Initialize Artemis client.

        Args:
            base_url: Artemis server URL (default: from DEFAULT_BASE_URL or ARTEMIS_BASE_URL env)
            api_key: Artemis API key (default: from DEFAULT_API_KEY or ARTEMIS_API_KEY env)
            app_id: Optional app identifier for usage tracking
            user_id: Optional user identifier for usage tracking
        """
        self.base_url = base_url or os.getenv("ARTEMIS_BASE_URL", self.DEFAULT_BASE_URL)
        self.api_key = api_key or os.getenv("ARTEMIS_API_KEY", self.DEFAULT_API_KEY)
        self.app_id = app_id
        self.user_id = user_id

        self._openai_client = None
        self._anthropic_client = None
        self._openrouter_client = None
        self._perplexity_client = None

    @property
    def openai(self):
        """Get OpenAI client configured for Artemis."""
        if self._openai_client is None:
            from openai import OpenAI
            self._openai_client = OpenAI(
                base_url=f"{{self.base_url}}/v1/openai",
                api_key=self.api_key,
                default_headers=self._get_tracking_headers(),
            )
        return self._openai_client

    @property
    def anthropic(self):
        """Get Anthropic client configured for Artemis."""
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.Anthropic(
                base_url=f"{{self.base_url}}/v1/anthropic",
                api_key=self.api_key,
                default_headers=self._get_tracking_headers(),
            )
        return self._anthropic_client

    @property
    def openrouter(self):
        """Get OpenRouter client (OpenAI-compatible) configured for Artemis."""
        if self._openrouter_client is None:
            from openai import OpenAI
            self._openrouter_client = OpenAI(
                base_url=f"{{self.base_url}}/v1/openrouter",
                api_key=self.api_key,
                default_headers=self._get_tracking_headers(),
            )
        return self._openrouter_client

    @property
    def perplexity(self):
        """Get Perplexity client (OpenAI-compatible) configured for Artemis."""
        if self._perplexity_client is None:
            from openai import OpenAI
            self._perplexity_client = OpenAI(
                base_url=f"{{self.base_url}}/v1/perplexity",
                api_key=self.api_key,
                default_headers=self._get_tracking_headers(),
            )
        return self._perplexity_client

    def _get_tracking_headers(self) -> dict:
        """Get headers for usage tracking."""
        headers = {{}}
        if self.app_id:
            headers["X-App-ID"] = self.app_id
        if self.user_id:
            headers["X-User-ID"] = self.user_id
        return headers

    def chat(
        self,
        messages: list,
        model: str = "gpt-4o",
        provider: str = "openai",
        **kwargs
    ):
        """
        Simplified chat interface that works across providers.

        Args:
            messages: List of message dicts with role and content
            model: Model name (default: gpt-4o)
            provider: Provider to use (openai, anthropic, openrouter, perplexity)
            **kwargs: Additional arguments passed to the API

        Returns:
            The response from the provider
        """
        if provider == "openai":
            return self.openai.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
        elif provider == "anthropic":
            # Convert to Anthropic format
            system = None
            anthropic_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system = msg["content"]
                else:
                    anthropic_messages.append(msg)

            return self.anthropic.messages.create(
                model=model,
                messages=anthropic_messages,
                system=system,
                max_tokens=kwargs.get("max_tokens", 1024),
                **{{k: v for k, v in kwargs.items() if k != "max_tokens"}}
            )
        elif provider == "openrouter":
            return self.openrouter.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
        elif provider == "perplexity":
            return self.perplexity.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
        else:
            raise ValueError(f"Unknown provider: {{provider}}")


# Convenience function for quick setup
def get_client(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    app_id: Optional[str] = None,
) -> ArtemisClient:
    """
    Quick setup for getting a configured client.

    Args:
        base_url: Optional Artemis URL override
        api_key: Optional API key override
        app_id: Optional app ID for tracking

    Returns:
        Configured ArtemisClient instance

    Example:
        client = get_client()
        response = client.openai.chat.completions.create(
            model="gpt-4o",
            messages=[{{"role": "user", "content": "Hello!"}}]
        )
    """
    return ArtemisClient(base_url=base_url, api_key=api_key, app_id=app_id)


if __name__ == "__main__":
    # Quick test
    client = ArtemisClient(app_id="artemis-test")
    print(f"Artemis client configured for: {{client.base_url}}")
    print(f"API Key: {{client.api_key[:20]}}..." if client.api_key else "No API key set")
'''

    return PlainTextResponse(
        content=client_code,
        media_type="text/x-python",
        headers={"Content-Disposition": "attachment; filename=artemis_client.py"}
    )


@router.get("/api/agent-setup")
async def agent_setup_public(request: Request):
    """
    Public endpoint for AI agents to begin Artemis setup.

    No authentication required. Returns instructions that tell the agent to:
    1. Ask the user for their Artemis API key
    2. Call /api/agent-setup/configure with the key to get full config

    This is the entry point for agents that don't yet have a key.
    """
    # Determine base URL from request
    host = request.headers.get("host", "localhost:8000")
    scheme = "https" if not host.startswith("localhost") and not host.startswith("127.") else "http"
    base_url = f"{scheme}://{host}"

    return JSONResponse({
        "service": "Artemis LLM Proxy",
        "description": "Unified proxy for OpenAI, Anthropic, and other LLM providers with usage tracking and cost management.",
        "setup_instructions": {
            "description": "Steps to configure Artemis for this project",
            "why": "Artemis routes all LLM requests through a single API key, enabling usage tracking, cost management, and provider failover.",
            "steps": [
                {
                    "step": 1,
                    "action": "ask_user",
                    "description": "Ask the user for their Artemis API key",
                    "why": "The API key is a secret credential that only the user should provide. Never hardcode or assume the key value.",
                    "prompt": "Please provide your Artemis API key (starts with 'art_'). You can get one from your Artemis dashboard.",
                    "store_as": "ARTEMIS_API_KEY",
                    "validation": "^art_[a-zA-Z0-9]{20,}$",
                },
                {
                    "step": 2,
                    "action": "api_call",
                    "description": "Get full configuration from Artemis",
                    "why": "The authenticated endpoint returns provider URLs and validated configuration for your key.",
                    "method": "GET",
                    "url": f"{base_url}/api/agent-setup/configure",
                    "headers": {
                        "Authorization": "Bearer {ARTEMIS_API_KEY}"
                    },
                    "use_response_for": "remaining_steps",
                },
            ],
        },
    })


@router.get("/api/agent-setup/configure")
async def agent_setup_configure(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticated endpoint for AI agents to get full Artemis configuration.

    Authentication: Bearer token (Artemis API key) in Authorization header.

    Returns the complete setup configuration including:
    - Detailed explanation of how Artemis works
    - Provider endpoints
    - .env file content to write
    - Python client download URL
    - SDK configuration examples
    """
    from app.models import APIKey
    from app.auth import decrypt_api_key

    # Get API key from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            {"error": "Missing or invalid Authorization header. Use: Bearer <api_key>"},
            status_code=401
        )

    api_key_value = auth_header[7:]  # Remove "Bearer " prefix

    # Validate the API key
    result = await db.execute(
        select(APIKey).where(
            APIKey.key_prefix == api_key_value[:12],
            APIKey.revoked_at.is_(None)
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        return JSONResponse({"error": "Invalid API key"}, status_code=401)

    # Verify the full key matches
    try:
        stored_key = decrypt_api_key(api_key.encrypted_key)
        if stored_key != api_key_value:
            return JSONResponse({"error": "Invalid API key"}, status_code=401)
    except Exception:
        return JSONResponse({"error": "Invalid API key"}, status_code=401)

    # Determine base URL from request
    host = request.headers.get("host", "localhost:8000")
    scheme = "https" if not host.startswith("localhost") and not host.startswith("127.") else "http"
    base_url = f"{scheme}://{host}"

    # Build response with full configuration
    return JSONResponse({
        "status": "authenticated",
        "key_name": api_key.name,
        "key_prefix": api_key.key_prefix,

        # Detailed explanation of what Artemis is and how it works
        "artemis": {
            "name": "Artemis LLM Proxy",
            "what_it_is": "Artemis is a unified proxy server that sits between your application and LLM providers (OpenAI, Anthropic, OpenRouter, Perplexity, Google). All requests go through Artemis - you never call providers directly.",
            "how_it_works": {
                "summary": "Your app sends requests to Artemis using your Artemis API key. Artemis authenticates you, selects the appropriate provider API key from its secure storage, forwards your request to the provider, and returns the response.",
                "request_flow": [
                    "1. Your app makes a request to Artemis (e.g., POST {base_url}/v1/openai/chat/completions)",
                    "2. Artemis validates your Artemis API key (the art_xxx key)",
                    "3. Artemis looks up the actual provider API key (OpenAI, Anthropic, etc.) from its secure database",
                    "4. Artemis forwards your request to the real provider API",
                    "5. Artemis logs the request for usage tracking and cost management",
                    "6. Artemis returns the provider's response to your app"
                ],
                "key_concept": "You only need ONE API key (your Artemis key). Artemis handles all the provider keys internally. This allows organizations to manage API access, track costs, and control which models users can access."
            },
            "why_use_it": [
                "Unified API key management - one key for all providers",
                "Usage tracking and cost allocation across teams",
                "Centralized provider key security - users never see actual provider keys",
                "Model access control - admins decide which models are available",
                "Request logging and analytics",
                "Future: failover, rate limiting, caching"
            ],
        },

        "base_url": base_url,

        "provider_endpoints": {
            "description": "These are the Artemis proxy endpoints. Use these instead of calling providers directly.",
            "important": "All requests go TO ARTEMIS at these URLs. Artemis then forwards to the actual provider.",
            "endpoints": {
                "openai": {
                    "base_url": f"{base_url}/v1/openai",
                    "example_full_url": f"{base_url}/v1/openai/chat/completions",
                    "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "o1-preview", "o1-mini"],
                },
                "anthropic": {
                    "base_url": f"{base_url}/v1/anthropic",
                    "example_full_url": f"{base_url}/v1/anthropic/v1/messages",
                    "models": ["claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
                },
                "openrouter": {
                    "base_url": f"{base_url}/v1/openrouter",
                    "example_full_url": f"{base_url}/v1/openrouter/chat/completions",
                    "note": "OpenRouter provides access to many models from various providers",
                },
                "perplexity": {
                    "base_url": f"{base_url}/v1/perplexity",
                    "example_full_url": f"{base_url}/v1/perplexity/chat/completions",
                    "models": ["llama-3.1-sonar-large-128k-online", "llama-3.1-sonar-small-128k-online"],
                },
                "google": {
                    "base_url": f"{base_url}/v1/google",
                    "example_full_url": f"{base_url}/v1/google/v1beta/models/gemini-pro:generateContent",
                    "models": ["gemini-pro", "gemini-pro-vision"],
                },
            },
        },

        "models_endpoint": {
            "description": "To discover available models, call this endpoint",
            "url": f"{base_url}/api/models",
            "method": "GET",
            "authentication": "Bearer token (same Artemis API key)",
            "why": "Models are configured per-organization in Artemis. This endpoint returns which models your API key has access to.",
        },

        "setup_instructions": {
            "description": "Complete the Artemis setup in your project",
            "why": "These steps configure your project to use Artemis for all LLM requests instead of calling providers directly.",
            "steps": [
                {
                    "step": 1,
                    "action": "write_file",
                    "description": "Write environment variables to a gitignored .env file",
                    "why": "Storing credentials in .env keeps them out of version control and allows the SDK to load them automatically via os.getenv(). The ARTEMIS_BASE_URL tells SDKs to route through Artemis.",
                    "target_path": ".env",
                    "content": f"# Artemis LLM Proxy Configuration\n# Key: {api_key.name}\n# All LLM requests go through Artemis - not directly to providers\nARTEMIS_API_KEY={{ARTEMIS_API_KEY}}\nARTEMIS_BASE_URL={base_url}\n",
                    "ensure_gitignore": True,
                },
                {
                    "step": 2,
                    "action": "download_file",
                    "description": "Download the Artemis Python client (optional but recommended)",
                    "why": "The client provides a unified interface to all providers with automatic base_url configuration. It's a drop-in replacement that routes through Artemis.",
                    "source_url": f"{base_url}/downloads/artemis_client.py",
                    "suggested_target": "artemis_client.py",
                },
                {
                    "step": 3,
                    "action": "configure_sdk",
                    "description": "Configure OpenAI/Anthropic SDK to use Artemis proxy",
                    "why": "Setting base_url to Artemis routes all SDK requests through the proxy. You use your Artemis API key (not provider keys) for authentication.",
                    "critical_understanding": "The api_key parameter takes your ARTEMIS key (art_xxx), NOT an OpenAI/Anthropic key. Artemis handles the real provider authentication internally.",
                    "openai_example": {
                        "code": f'''from openai import OpenAI
import os

# All requests go through Artemis proxy
client = OpenAI(
    base_url="{base_url}/v1/openai",  # Artemis proxy URL, NOT api.openai.com
    api_key=os.getenv("ARTEMIS_API_KEY")  # Your Artemis key, NOT an OpenAI key
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{{"role": "user", "content": "Hello!"}}]
)''',
                        "explanation": "This sends the request to Artemis at {base_url}/v1/openai/chat/completions. Artemis validates your Artemis key, then uses its stored OpenAI key to call api.openai.com.",
                    },
                    "anthropic_example": {
                        "code": f'''import anthropic
import os

# All requests go through Artemis proxy
client = anthropic.Anthropic(
    base_url="{base_url}/v1/anthropic",  # Artemis proxy URL, NOT api.anthropic.com
    api_key=os.getenv("ARTEMIS_API_KEY")  # Your Artemis key, NOT an Anthropic key
)

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{{"role": "user", "content": "Hello!"}}]
)''',
                        "explanation": "This sends the request to Artemis at {base_url}/v1/anthropic/v1/messages. Artemis validates your Artemis key, then uses its stored Anthropic key to call api.anthropic.com.",
                    },
                    "artemis_client_example": {
                        "code": f'''from artemis_client import ArtemisClient
import os

# ArtemisClient automatically configures base_url for all providers
client = ArtemisClient()

# Use OpenAI models through Artemis
response = client.openai.chat.completions.create(
    model="gpt-4o",
    messages=[{{"role": "user", "content": "Hello!"}}]
)

# Or use Anthropic models through Artemis
response = client.anthropic.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{{"role": "user", "content": "Hello!"}}]
)''',
                        "explanation": "The ArtemisClient helper automatically routes to the correct Artemis endpoint for each provider.",
                    },
                },
            ],
        },

        "common_mistakes": [
            {
                "mistake": "Using provider API keys (sk-xxx, sk-ant-xxx) instead of Artemis key",
                "correct": "Always use your Artemis API key (art_xxx). Artemis handles provider authentication.",
            },
            {
                "mistake": "Setting base_url to the provider's URL (api.openai.com)",
                "correct": f"Set base_url to Artemis ({base_url}/v1/openai). Artemis forwards to the provider.",
            },
            {
                "mistake": "Calling provider APIs directly",
                "correct": "All requests must go through Artemis for tracking and key management.",
            },
        ],
    })


@router.get("/api/models")
async def api_models(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Get available models for the authenticated API key.

    Authentication: Bearer token (Artemis API key) in Authorization header.

    Returns list of enabled models organized by provider, with metadata
    useful for AI agents to select appropriate models.
    """
    from app.models import APIKey, ProviderAccount, ProviderKey
    from app.auth import decrypt_api_key
    from app.services.provider_model_service import ProviderModelService

    # Get API key from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            {"error": "Missing or invalid Authorization header. Use: Bearer <api_key>"},
            status_code=401
        )

    api_key_value = auth_header[7:]  # Remove "Bearer " prefix

    # Validate the API key
    result = await db.execute(
        select(APIKey).where(
            APIKey.key_prefix == api_key_value[:12],
            APIKey.revoked_at.is_(None)
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        return JSONResponse({"error": "Invalid API key"}, status_code=401)

    # Verify the full key matches
    try:
        stored_key = decrypt_api_key(api_key.encrypted_key)
        if stored_key != api_key_value:
            return JSONResponse({"error": "Invalid API key"}, status_code=401)
    except Exception:
        return JSONResponse({"error": "Invalid API key"}, status_code=401)

    # Determine base URL from request
    host = request.headers.get("host", "localhost:8000")
    scheme = "https" if not host.startswith("localhost") and not host.startswith("127.") else "http"
    base_url = f"{scheme}://{host}"

    # Get available providers based on API key's group
    available_provider_ids = []
    if api_key.group_id:
        provider_keys_result = await db.execute(
            select(ProviderAccount.provider_id)
            .join(ProviderKey, ProviderKey.provider_account_id == ProviderAccount.id)
            .where(ProviderAccount.group_id == api_key.group_id)
            .distinct()
        )
        available_provider_ids = [row[0] for row in provider_keys_result]

    # Get enabled models from database
    provider_model_service = ProviderModelService(db)
    enabled_models = await provider_model_service.get_enabled_models(
        provider_ids=available_provider_ids if available_provider_ids else None
    )

    # Organize models by provider
    provider_names = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "google": "Google",
        "perplexity": "Perplexity",
        "openrouter": "OpenRouter",
    }

    models_by_provider = {}
    for model in enabled_models:
        provider_id = model.provider_id
        if provider_id not in models_by_provider:
            models_by_provider[provider_id] = {
                "provider_name": provider_names.get(provider_id, provider_id.title()),
                "base_url": f"{base_url}/v1/{provider_id}",
                "models": [],
            }

        # Extract capabilities from raw_data
        supports_vision = False
        supports_function_calling = False
        if model.raw_data:
            input_modalities = model.raw_data.get("architecture", {}).get("input_modalities", [])
            supports_vision = "image" in input_modalities
            # Most recent models support function calling
            supports_function_calling = model.raw_data.get("supports_functions", True)

        models_by_provider[provider_id]["models"].append({
            "model_id": model.model_id,
            "name": model.name,
            "description": model.description,
            "context_length": model.context_length,
            "max_completion_tokens": model.max_completion_tokens,
            "supports_vision": supports_vision,
            "supports_function_calling": supports_function_calling,
            "pricing": {
                "input_per_1m_tokens_cents": model.input_price_per_1m,
                "output_per_1m_tokens_cents": model.output_price_per_1m,
            } if model.input_price_per_1m or model.output_price_per_1m else None,
        })

    return JSONResponse({
        "description": "Available models for your Artemis API key",
        "how_to_use": {
            "explanation": "Use these model IDs with the corresponding provider endpoint. All requests go through Artemis - not directly to providers.",
            "example": {
                "provider": "openai",
                "base_url": f"{base_url}/v1/openai",
                "model": "gpt-4o",
                "note": "Use your Artemis API key (art_xxx), not an OpenAI key",
            },
        },
        "providers": models_by_provider,
        "total_models": len(enabled_models),
    })
