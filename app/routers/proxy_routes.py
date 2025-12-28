"""
Proxy routes for LLM provider requests.

Handles request forwarding with:
- Authentication validation
- Provider key management
- Error handling with graceful failures
- Health tracking
- Usage logging
"""

import time
import json
import logging
import traceback
import uuid
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import APIKey, ProviderKey, ProviderAccount, UsageLog, AppLog
from app.auth import decrypt_api_key
from app.config import settings
from app.providers.pricing import calculate_cost, get_fallback_pricing
from app.services.provider_health import provider_health
from app.services.request_log_service import RequestLogService, generate_request_id
from app.services.provider_model_service import ProviderModelService


async def log_proxy_error(
    db: AsyncSession,
    error_type: str,
    message: str,
    provider: str,
    request_id: str,
    extra_data: dict = None,
):
    """Log proxy errors to app_logs for unified debugging (localhost mode only)."""
    if not settings.LOCALHOST_MODE:
        return

    try:
        log_entry = AppLog(
            source="backend",
            level="error",
            message=message,
            error_type=error_type,
            page=f"/v1/{provider}",
            component="proxy_routes",
            extra_data={
                "request_id": request_id,
                "provider": provider,
                **(extra_data or {}),
            },
        )
        db.add(log_entry)
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to log proxy error to app_logs: {e}")

router = APIRouter()
logger = logging.getLogger(__name__)

# App IDs that always get full content logging (request + response bodies)
FULL_LOGGING_APP_IDS = {"artemis-chat", "artemis-vision"}

# Provider-specific timeouts (seconds)
PROVIDER_TIMEOUTS = {
    "openai": 120.0,
    "anthropic": 180.0,  # Claude can be slower for complex tasks
    "google": 120.0,
    "perplexity": 60.0,
    "openrouter": 120.0,
}
DEFAULT_TIMEOUT = 120.0


def make_error_response(
    status_code: int,
    error_type: str,
    message: str,
    provider: str = None,
    request_id: str = None,
    category: str = None,
    recovery: dict = None,
    context: dict = None,
) -> JSONResponse:
    """
    Create an agent-friendly error response with structured metadata.

    Categories:
    - transient: Retry may succeed (rate limits, timeouts, temporary failures)
    - permanent: Won't succeed without changes (invalid model, auth error)
    - policy: Blocked by policy (content filter, budget exceeded)
    - upstream: Provider-side issue

    Recovery actions:
    - retry: Simple retry
    - retry_with_backoff: Retry with exponential backoff
    - switch_provider: Try a different provider
    - reduce_tokens: Request is too large
    - check_api_key: API key issue
    - contact_support: Unrecoverable error
    """
    # Infer category from error type if not provided
    if category is None:
        if error_type in ("timeout", "connection_error", "stream_error"):
            category = "transient"
        elif error_type in ("rate_limited", "provider_overloaded"):
            category = "transient"
        elif error_type in ("invalid_api_key", "invalid_provider", "model_disabled"):
            category = "permanent"
        elif error_type in ("budget_exceeded", "content_filtered"):
            category = "policy"
        elif error_type in ("provider_error", "http_error"):
            category = "upstream"
        else:
            category = "unknown"

    # Build recovery suggestion if not provided
    if recovery is None:
        if category == "transient":
            recovery = {
                "action": "retry_with_backoff",
                "delay_ms": 1000,
                "max_retries": 3,
            }
            if provider:
                # Suggest alternative providers
                alternatives = [p for p in ["openai", "anthropic", "google"] if p != provider]
                recovery["alternative_providers"] = alternatives
        elif error_type == "invalid_api_key":
            recovery = {
                "action": "check_api_key",
                "docs": "/guide/api-keys",
            }
        elif error_type == "model_disabled":
            recovery = {
                "action": "list_models",
                "endpoint": "/v1/models",
            }

    error_body = {
        "error": {
            "code": error_type.upper(),
            "message": message,
            "type": error_type,
            "category": category,
        }
    }

    if provider:
        error_body["error"]["provider"] = provider
    if request_id:
        error_body["error"]["request_id"] = request_id
    if recovery:
        error_body["error"]["recovery"] = recovery
    if context:
        error_body["error"]["context"] = context

    return JSONResponse(status_code=status_code, content=error_body)


async def validate_api_key(
    request: Request, db: AsyncSession = Depends(get_db)
) -> tuple[APIKey, str]:
    """Validate Artemis API key from Authorization header."""
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    api_key_value = auth_header[7:]  # Remove "Bearer "

    if not api_key_value.startswith("art_"):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    # Hash and lookup
    import hashlib
    key_hash = hashlib.sha256(api_key_value.encode()).hexdigest()

    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.revoked_at.is_(None))
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    # Update last used
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return api_key, api_key.user_id


async def get_provider_key(
    user_id: str, provider: str, db: AsyncSession, api_key: APIKey = None
) -> tuple[str, str]:
    """Get decrypted provider API key for user.

    Returns (decrypted_key, provider_key_id) tuple.
    Uses API key overrides if specified, otherwise uses default.

    If the API key belongs to a group, looks up provider keys from that group's scope.
    The new model has: ProviderKey -> ProviderAccount (has provider_id and group_id)
    """
    # Determine the group context from the API key
    group_id = api_key.group_id if api_key else None

    # Check if there's an override for this provider on the API key
    if api_key and api_key.provider_key_overrides:
        override_id = api_key.provider_key_overrides.get(provider)
        if override_id:
            # Use the specific provider key by ID
            result = await db.execute(
                select(ProviderKey)
                .join(ProviderAccount)
                .where(ProviderKey.id == override_id)
            )
            provider_key = result.scalar_one_or_none()
            if provider_key:
                return decrypt_api_key(provider_key.encrypted_key), provider_key.id

    # Build query joining through ProviderAccount for provider_id and group_id
    # ProviderKey -> ProviderAccount (has provider_id and group_id)
    query = (
        select(ProviderKey)
        .join(ProviderAccount)
        .where(ProviderAccount.provider_id == provider)
    )

    if group_id:
        query = query.where(ProviderAccount.group_id == group_id)

    # Fall back to default provider key (in same group scope)
    result = await db.execute(
        query.where(ProviderKey.is_default == True)
    )
    provider_key = result.scalar_one_or_none()

    # If no default, try to get any key for this provider (in same scope)
    if not provider_key:
        result = await db.execute(query.limit(1))
        provider_key = result.scalar_one_or_none()

    if not provider_key:
        scope_msg = " for this group" if group_id else ""
        raise HTTPException(
            status_code=400,
            detail=f"No {provider} API key configured{scope_msg}. Add it at /providers",
        )

    return decrypt_api_key(provider_key.encrypted_key), provider_key.id


async def log_usage(
    db: AsyncSession,
    api_key_id: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    provider_key_id: Optional[str] = None,
    app_id: Optional[str] = None,
    end_user_id: Optional[str] = None,
    request_metadata: Optional[dict] = None,
):
    """Log API usage."""
    cost_cents = calculate_cost(provider, model, input_tokens, output_tokens)

    usage_log = UsageLog(
        api_key_id=api_key_id,
        provider_key_id=provider_key_id,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_cents=cost_cents,
        latency_ms=latency_ms,
        app_id=app_id,
        end_user_id=end_user_id,
        request_metadata=request_metadata,
    )
    db.add(usage_log)
    await db.commit()


def extract_usage_from_response(provider: str, response_data: dict) -> tuple[str, int, int]:
    """Extract model and token counts from provider response."""
    model = "unknown"
    input_tokens = 0
    output_tokens = 0

    if provider == "openai":
        model = response_data.get("model", "unknown")
        usage = response_data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

    elif provider == "anthropic":
        model = response_data.get("model", "unknown")
        usage = response_data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

    elif provider == "google":
        # Gemini uses different structure
        model = response_data.get("modelVersion", "unknown")
        usage = response_data.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount", 0)
        output_tokens = usage.get("candidatesTokenCount", 0)

    elif provider == "perplexity":
        model = response_data.get("model", "unknown")
        usage = response_data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

    elif provider == "openrouter":
        model = response_data.get("model", "unknown")
        usage = response_data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

    return model, input_tokens, output_tokens


@router.api_route("/v1/{provider}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(
    provider: str,
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Pass-through proxy to LLM providers with error handling and health tracking.

    Returns errors in OpenAI-compatible format so SDK clients can handle them.
    """
    # Generate request ID for tracing
    request_id = generate_request_id()

    # Initialize request log service
    request_log_service = RequestLogService(db)

    # Validate our API key
    api_key, user_id = await validate_api_key(request, db)

    # Get provider URL
    if provider not in settings.PROVIDER_URLS:
        return make_error_response(
            400, "invalid_provider", f"Unknown provider: {provider}",
            request_id=request_id
        )

    base_url = settings.PROVIDER_URLS[provider]
    target_url = f"{base_url}/{path}"

    # Get user's provider key (with overrides if configured)
    try:
        provider_api_key, provider_key_id = await get_provider_key(user_id, provider, db, api_key)
    except HTTPException as e:
        return make_error_response(
            e.status_code, "configuration_error", e.detail,
            provider=provider, request_id=request_id
        )

    # Build headers for upstream request
    headers = {}
    for key, value in request.headers.items():
        # Skip hop-by-hop headers and our auth header
        if key.lower() not in ("host", "authorization", "content-length", "transfer-encoding"):
            headers[key] = value

    # Set provider-specific auth header
    if provider == "openai":
        headers["Authorization"] = f"Bearer {provider_api_key}"
    elif provider == "anthropic":
        headers["x-api-key"] = provider_api_key
        headers["anthropic-version"] = headers.get("anthropic-version", "2023-06-01")
    elif provider == "google":
        # Google uses query param for API key
        if "?" in target_url:
            target_url += f"&key={provider_api_key}"
        else:
            target_url += f"?key={provider_api_key}"
    elif provider == "perplexity":
        headers["Authorization"] = f"Bearer {provider_api_key}"
    elif provider == "openrouter":
        headers["Authorization"] = f"Bearer {provider_api_key}"

    # Get request body
    body = await request.body()

    # Check if streaming is requested and extract tracking metadata
    is_streaming = False
    app_id = None
    end_user_id = None

    if body:
        try:
            body_json = json.loads(body)
            is_streaming = body_json.get("stream", False)
            # Extract tracking metadata from request body
            metadata = body_json.get("metadata", {})
            app_id = metadata.get("app_id") or body_json.get("app_id")
            end_user_id = metadata.get("user_id") or body_json.get("user")
        except json.JSONDecodeError:
            pass

    # Also check headers for tracking info
    if not app_id:
        app_id = request.headers.get("x-app-id")
    if not end_user_id:
        end_user_id = request.headers.get("x-user-id")

    # Determine if full content logging is enabled
    # Full logging captures complete request/response bodies for debugging
    log_full_header = request.headers.get("x-artemis-log-full", "").lower()
    log_full_content = (
        log_full_header in ("true", "1", "yes") or
        app_id in FULL_LOGGING_APP_IDS
    )

    start_time = time.time()
    timeout = PROVIDER_TIMEOUTS.get(provider, DEFAULT_TIMEOUT)

    # Extract client info
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Extract model from request body if available
    request_model = None
    if body:
        try:
            body_json = json.loads(body)
            request_model = body_json.get("model")
        except json.JSONDecodeError:
            pass

    # Validate model is enabled (if model specified and we have model restrictions)
    if request_model:
        model_service = ProviderModelService(db)
        is_allowed = await model_service.is_model_enabled(provider, request_model)
        if not is_allowed:
            logger.warning(
                f"Model access denied: {request_model}",
                extra={
                    "request_id": request_id,
                    "provider": provider,
                    "model": request_model,
                }
            )
            return make_error_response(
                403, "model_disabled",
                f"Model '{request_model}' is not enabled for use. Check /api/models for available models.",
                provider=provider, request_id=request_id
            )

    # Build request metadata - include full body if full logging enabled
    req_metadata = {"path": path}
    if log_full_content and body:
        try:
            # Try to store as parsed JSON for better readability
            req_metadata["body"] = json.loads(body)
        except json.JSONDecodeError:
            # Fall back to string if not valid JSON
            req_metadata["body"] = body.decode("utf-8", errors="replace")

    # Log the request start to DB
    try:
        request_log = await request_log_service.start_request(
            request_id=request_id,
            provider=provider,
            endpoint=f"/v1/{provider}/{path}",
            api_key_id=api_key.id,
            model=request_model,
            method=request.method,
            is_streaming=is_streaming,
            app_id=app_id,
            client_ip=client_ip,
            user_agent=user_agent,
            request_metadata=req_metadata,
        )
        request_log_id = request_log.id
    except Exception as log_error:
        logger.error(f"Failed to log request start: {log_error}")
        request_log_id = None

    # Log the request (console)
    logger.info(
        f"Proxying request to {provider}",
        extra={
            "request_id": request_id,
            "provider": provider,
            "path": path,
            "streaming": is_streaming,
            "app_id": app_id,
        }
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if is_streaming:
                return await handle_streaming_request(
                    client, request, target_url, headers, body, provider,
                    api_key, provider_key_id, app_id, end_user_id,
                    start_time, request_id, request_log_id, request_log_service, db,
                    log_full_content, request_model
                )
            else:
                return await handle_non_streaming_request(
                    client, request, target_url, headers, body, provider,
                    api_key, provider_key_id, app_id, end_user_id,
                    start_time, request_id, request_log_id, request_log_service, db,
                    log_full_content, request_model
                )

    except httpx.TimeoutException:
        latency_ms = int((time.time() - start_time) * 1000)
        provider_health.record_failure(provider, "timeout", f"Request timed out after {timeout}s", latency_ms)

        # Log failure to DB
        if request_log_id:
            try:
                await request_log_service.fail_request(
                    request_log_id, "timeout",
                    f"Request timed out after {timeout}s",
                    status_code=504, latency_ms=latency_ms
                )
            except Exception:
                pass

        # Log to app_logs for unified debugging
        await log_proxy_error(
            db, "timeout",
            f"{provider} request timed out after {int(timeout)}s",
            provider, request_id,
            {"timeout_seconds": timeout, "latency_ms": latency_ms, "model": request_model}
        )

        logger.error(
            f"Provider timeout: {provider}",
            extra={
                "request_id": request_id,
                "provider": provider,
                "timeout_seconds": timeout,
                "latency_ms": latency_ms,
            }
        )

        return make_error_response(
            504, "timeout",
            f"{provider} request timed out after {int(timeout)} seconds. The provider may be experiencing high load.",
            provider=provider, request_id=request_id
        )

    except httpx.ConnectError as e:
        latency_ms = int((time.time() - start_time) * 1000)
        provider_health.record_failure(provider, "connection_error", str(e), latency_ms)

        # Log failure to DB
        if request_log_id:
            try:
                await request_log_service.fail_request(
                    request_log_id, "connection_error",
                    str(e), status_code=502, latency_ms=latency_ms
                )
            except Exception:
                pass

        # Log to app_logs for unified debugging
        await log_proxy_error(
            db, "connection_error",
            f"Cannot connect to {provider}: {str(e)}",
            provider, request_id,
            {"error": str(e), "latency_ms": latency_ms, "model": request_model}
        )

        logger.error(
            f"Provider connection error: {provider}",
            extra={
                "request_id": request_id,
                "provider": provider,
                "error": str(e),
            }
        )

        return make_error_response(
            502, "connection_error",
            f"Cannot connect to {provider}. The provider may be down or unreachable.",
            provider=provider, request_id=request_id
        )

    except httpx.HTTPStatusError as e:
        latency_ms = int((time.time() - start_time) * 1000)
        provider_health.record_failure(provider, "http_error", f"HTTP {e.response.status_code}", latency_ms)

        # Log failure to DB
        if request_log_id:
            try:
                await request_log_service.fail_request(
                    request_log_id, "http_error",
                    f"HTTP {e.response.status_code}",
                    status_code=e.response.status_code, latency_ms=latency_ms
                )
            except Exception:
                pass

        # Log to app_logs for unified debugging
        await log_proxy_error(
            db, "http_error",
            f"{provider} returned HTTP {e.response.status_code}",
            provider, request_id,
            {"status_code": e.response.status_code, "latency_ms": latency_ms, "model": request_model}
        )

        logger.error(
            f"Provider HTTP error: {provider}",
            extra={
                "request_id": request_id,
                "provider": provider,
                "status_code": e.response.status_code,
            }
        )

        # Pass through the provider's error response if possible
        try:
            error_body = e.response.json()
            return JSONResponse(status_code=e.response.status_code, content=error_body)
        except Exception:
            return make_error_response(
                e.response.status_code, "provider_error",
                f"{provider} returned HTTP {e.response.status_code}",
                provider=provider, request_id=request_id
            )

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        provider_health.record_failure(provider, "unknown_error", str(e), latency_ms)

        # Log failure to DB
        if request_log_id:
            try:
                await request_log_service.fail_request(
                    request_log_id, "unknown_error",
                    str(e), status_code=500, latency_ms=latency_ms
                )
            except Exception:
                pass

        # Log to app_logs for unified debugging
        await log_proxy_error(
            db, "unknown_error",
            f"Unexpected error proxying to {provider}: {str(e)}",
            provider, request_id,
            {"error": str(e), "traceback": traceback.format_exc(), "latency_ms": latency_ms, "model": request_model}
        )

        logger.exception(
            f"Unexpected error proxying to {provider}",
            extra={
                "request_id": request_id,
                "provider": provider,
                "error": str(e),
            }
        )

        return make_error_response(
            500, "internal_error",
            f"An unexpected error occurred while processing your request to {provider}.",
            provider=provider, request_id=request_id
        )


async def handle_streaming_request(
    client: httpx.AsyncClient,
    request: Request,
    target_url: str,
    headers: dict,
    body: bytes,
    provider: str,
    api_key: APIKey,
    provider_key_id: str,
    app_id: Optional[str],
    end_user_id: Optional[str],
    start_time: float,
    request_id: str,
    request_log_id: Optional[str],
    request_log_service: RequestLogService,
    db: AsyncSession,
    log_full_content: bool = False,
    request_model: Optional[str] = None,
) -> StreamingResponse:
    """Handle streaming request with error tracking."""

    async def stream_and_log():
        accumulated_data = []
        accumulated_content = []  # For full logging - accumulate text content
        error_occurred = False
        error_message = None
        response_status_code = 200

        try:
            async with client.stream(
                request.method,
                target_url,
                headers=headers,
                content=body,
            ) as response:
                response_status_code = response.status_code
                # Check for error response
                if response.status_code >= 400:
                    error_occurred = True
                    error_content = await response.aread()
                    error_message = f"HTTP {response.status_code}"
                    try:
                        error_json = json.loads(error_content)
                        yield error_content
                        return
                    except json.JSONDecodeError:
                        yield error_content
                        return

                async for chunk in response.aiter_bytes():
                    yield chunk
                    # Try to parse SSE data for usage info and content
                    try:
                        chunk_str = chunk.decode()
                        for line in chunk_str.split("\n"):
                            if line.startswith("data: ") and line != "data: [DONE]":
                                data = json.loads(line[6:])
                                accumulated_data.append(data)
                                # Extract text content for full logging
                                if log_full_content:
                                    # OpenAI/compatible format
                                    delta = data.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content")
                                    if content:
                                        accumulated_content.append(content)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass

        except httpx.TimeoutException:
            error_occurred = True
            error_message = "Stream timed out"
            error_response = json.dumps({
                "error": {
                    "message": f"{provider} stream timed out",
                    "type": "timeout",
                    "provider": provider,
                    "request_id": request_id,
                }
            })
            yield f"data: {error_response}\n\n".encode()

        except Exception as e:
            error_occurred = True
            error_message = str(e)
            error_response = json.dumps({
                "error": {
                    "message": f"Stream error: {str(e)}",
                    "type": "stream_error",
                    "provider": provider,
                    "request_id": request_id,
                }
            })
            yield f"data: {error_response}\n\n".encode()

        finally:
            # Log after stream completes
            latency_ms = int((time.time() - start_time) * 1000)

            if error_occurred:
                provider_health.record_failure(provider, "stream_error", error_message or "Unknown", latency_ms)
                # Log failure to DB
                if request_log_id:
                    try:
                        await request_log_service.fail_request(
                            request_log_id, "stream_error",
                            error_message or "Unknown",
                            status_code=response_status_code, latency_ms=latency_ms
                        )
                    except Exception:
                        pass
            else:
                provider_health.record_success(provider, latency_ms)
                # Log success to DB with full response if enabled
                if request_log_id:
                    try:
                        resp_metadata = None
                        if log_full_content and accumulated_content:
                            resp_metadata = {"content": "".join(accumulated_content)}
                        await request_log_service.complete_request(
                            request_log_id, response_status_code, latency_ms,
                            response_metadata=resp_metadata
                        )
                    except Exception:
                        pass

            # Extract model and usage from accumulated data
            # Use response model if available, fallback to request model
            model = request_model or "unknown"
            if accumulated_data and "model" in accumulated_data[0]:
                model = accumulated_data[0]["model"]

            input_tokens = 0
            output_tokens = 0
            for chunk in reversed(accumulated_data):
                if "usage" in chunk:
                    input_tokens = chunk["usage"].get("prompt_tokens", 0)
                    output_tokens = chunk["usage"].get("completion_tokens", 0)
                    break

            try:
                await log_usage(
                    db, api_key.id, provider, model,
                    input_tokens, output_tokens, latency_ms,
                    provider_key_id=provider_key_id,
                    app_id=app_id, end_user_id=end_user_id
                )
            except Exception as log_error:
                logger.error(f"Failed to log usage: {log_error}")

    return StreamingResponse(
        stream_and_log(),
        media_type="text/event-stream",
    )


async def handle_non_streaming_request(
    client: httpx.AsyncClient,
    request: Request,
    target_url: str,
    headers: dict,
    body: bytes,
    provider: str,
    api_key: APIKey,
    provider_key_id: str,
    app_id: Optional[str],
    end_user_id: Optional[str],
    start_time: float,
    request_id: str,
    request_log_id: Optional[str],
    request_log_service: RequestLogService,
    db: AsyncSession,
    log_full_content: bool = False,
    request_model: Optional[str] = None,
) -> Response:
    """Handle non-streaming request with error tracking."""

    response = await client.request(
        request.method,
        target_url,
        headers=headers,
        content=body,
    )

    latency_ms = int((time.time() - start_time) * 1000)

    # Track success/failure for health monitoring
    if response.status_code >= 400:
        provider_health.record_failure(
            provider, f"http_{response.status_code}",
            f"HTTP {response.status_code}", latency_ms
        )
    else:
        provider_health.record_success(provider, latency_ms)

    # Parse response for logging
    # Use request model as fallback when response doesn't contain model
    model = request_model or "unknown"
    input_tokens = 0
    output_tokens = 0
    response_data = None
    cost_cents = 0

    try:
        response_data = response.json()
        resp_model, input_tokens, output_tokens = extract_usage_from_response(
            provider, response_data
        )
        # Only override if response had a model
        if resp_model != "unknown":
            model = resp_model
        # Calculate cost
        cost_cents = calculate_cost(provider, model, input_tokens, output_tokens)
    except (json.JSONDecodeError, Exception):
        pass

    # Log success/failure to DB with full response if enabled
    if request_log_id:
        try:
            if response.status_code >= 400:
                await request_log_service.fail_request(
                    request_log_id, f"http_{response.status_code}",
                    f"HTTP {response.status_code}",
                    status_code=response.status_code, latency_ms=latency_ms
                )
            else:
                resp_metadata = None
                if log_full_content and response_data:
                    # Extract just the content for cleaner logging
                    content = None
                    if response_data.get("choices"):
                        content = response_data["choices"][0].get("message", {}).get("content")
                    resp_metadata = {"body": response_data} if not content else {"content": content, "body": response_data}
                await request_log_service.complete_request(
                    request_log_id, response.status_code, latency_ms,
                    response_metadata=resp_metadata
                )
        except Exception:
            pass

    # Log usage
    try:
        await log_usage(
            db, api_key.id, provider, model,
            input_tokens, output_tokens, latency_ms,
            provider_key_id=provider_key_id,
            app_id=app_id, end_user_id=end_user_id
        )
    except Exception as log_error:
        logger.error(f"Failed to log usage: {log_error}")

    # Return response with original headers
    response_headers = {}
    for key, value in response.headers.items():
        if key.lower() not in ("content-encoding", "transfer-encoding", "content-length"):
            response_headers[key] = value

    # Add our request ID for tracing
    response_headers["x-artemis-request-id"] = request_id

    # Add agent-friendly headers
    response_headers["x-artemis-provider"] = provider
    response_headers["x-artemis-model"] = model
    response_headers["x-artemis-latency-ms"] = str(latency_ms)
    response_headers["x-artemis-cost-cents"] = str(cost_cents)
    response_headers["x-artemis-cost-usd"] = f"{cost_cents / 100:.6f}"

    # For JSON responses, inject _artemis metadata into the body
    response_content = response.content
    if response_data is not None and response.status_code < 400:
        # Add _artemis block with agent-friendly metadata
        response_data["_artemis"] = {
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "latency_ms": latency_ms,
            "cost": {
                "input_cents": round((input_tokens / 1_000_000) * get_fallback_pricing(provider, model)[0], 4),
                "output_cents": round((output_tokens / 1_000_000) * get_fallback_pricing(provider, model)[1], 4),
                "total_cents": cost_cents,
                "total_usd": round(cost_cents / 100, 6),
            },
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
            },
        }
        response_content = json.dumps(response_data).encode()

    return Response(
        content=response_content,
        status_code=response.status_code,
        headers=response_headers,
    )
