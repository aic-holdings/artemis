"""
Whisper audio transcription router.

Proxies audio transcription requests to Whisper providers (self-hosted, Groq, OpenAI).
Uses the same API key validation and usage tracking as the LLM proxy.
"""
import hashlib
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.auth import decrypt_api_key
from app.models import APIKey, ProviderKey, ProviderAccount, UsageLog, Group, GroupMember

router = APIRouter()

# Whisper provider configuration
WHISPER_PROVIDERS = {
    "whisper": {
        "name": "Self-hosted Whisper",
        "base_url": "https://whisper.meetrhea.com",
        "auth_type": None,  # No auth needed for self-hosted
        "model": "Systran/faster-whisper-large-v3",  # faster-whisper model
    },
    "groq": {
        "name": "Groq Whisper",
        "base_url": "https://api.groq.com/openai/v1",
        "auth_type": "bearer",
        "model": "whisper-large-v3-turbo",  # Groq's fast Whisper model
    },
    "openai": {
        "name": "OpenAI Whisper",
        "base_url": "https://api.openai.com/v1",
        "auth_type": "bearer",
        "model": "whisper-1",  # OpenAI's Whisper model
    },
}

# Provider fallback order
WHISPER_FALLBACK_ORDER = ["whisper", "groq", "openai"]


async def validate_api_key(
    api_key: str,
    db: AsyncSession,
) -> tuple[Optional[APIKey], Optional[str]]:
    """Validate an Artemis API key and return the key object.

    Returns:
        tuple: (api_key_obj, error_message)
    """
    if not api_key:
        return None, "Missing API key"

    # Remove 'Bearer ' prefix if present
    if api_key.startswith("Bearer "):
        api_key = api_key[7:]

    # Hash the key for lookup
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # Look up the key
    result = await db.execute(
        select(APIKey)
        .options(selectinload(APIKey.group))
        .where(APIKey.key_hash == key_hash, APIKey.revoked_at.is_(None))
    )
    api_key_obj = result.scalar_one_or_none()

    if not api_key_obj:
        return None, "Invalid API key"

    # Update last used
    api_key_obj.last_used_at = datetime.now(timezone.utc)

    return api_key_obj, None


async def get_provider_key(
    group_id: str,
    provider_id: str,
    db: AsyncSession,
) -> Optional[ProviderKey]:
    """Get the default provider key for a provider in a group."""
    # First try to get the one marked as default
    result = await db.execute(
        select(ProviderKey)
        .join(ProviderAccount)
        .where(
            ProviderAccount.group_id == group_id,
            ProviderAccount.provider_id == provider_id,
            ProviderKey.is_default == True,
            ProviderKey.is_active == True,
        )
    )
    key = result.scalar_one_or_none()
    if key:
        return key

    # Otherwise get the first active one
    result = await db.execute(
        select(ProviderKey)
        .join(ProviderAccount)
        .where(
            ProviderAccount.group_id == group_id,
            ProviderAccount.provider_id == provider_id,
            ProviderKey.is_active == True,
        )
        .order_by(ProviderKey.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def log_whisper_usage(
    db: AsyncSession,
    api_key_id: str,
    provider_key_id: Optional[str],
    provider: str,
    model: str,
    audio_duration_seconds: float,
    latency_ms: int,
    app_id: Optional[str] = None,
):
    """Log Whisper transcription usage."""
    # Whisper pricing is typically per minute of audio
    # Convert duration to "audio tokens" for tracking (1 token = 1 second)
    audio_tokens = int(audio_duration_seconds)

    usage_log = UsageLog(
        api_key_id=api_key_id,
        provider_key_id=provider_key_id,
        provider=provider,
        model=model,
        input_tokens=0,
        output_tokens=0,
        audio_input_tokens=audio_tokens,
        latency_ms=latency_ms,
        app_id=app_id,
        request_metadata={
            "type": "audio_transcription",
            "audio_duration_seconds": audio_duration_seconds,
        },
    )
    db.add(usage_log)
    await db.commit()


def make_error_response(error: str, status_code: int = 400) -> JSONResponse:
    """Create an OpenAI-compatible error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": error,
                "type": "invalid_request_error",
                "code": None,
            }
        },
    )


@router.post("/v1/audio/transcriptions")
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    model: str = Form(default="whisper-1"),
    language: Optional[str] = Form(default=None),
    prompt: Optional[str] = Form(default=None),
    response_format: str = Form(default="json"),
    temperature: float = Form(default=0.0),
    db: AsyncSession = Depends(get_db),
):
    """
    Transcribe audio using Whisper.

    Compatible with OpenAI's /v1/audio/transcriptions endpoint.
    Tries providers in order: self-hosted → Groq → OpenAI.
    """
    start_time = time.time()

    # Get API key from header
    auth_header = request.headers.get("Authorization", "")
    api_key_obj, error = await validate_api_key(auth_header, db)
    if error:
        return make_error_response(error, 401)

    # Get the group from the API key
    if not api_key_obj.group_id:
        return make_error_response("API key has no group assigned", 400)

    group_id = api_key_obj.group_id

    # Read the audio file
    audio_content = await file.read()
    file_size = len(audio_content)

    # Estimate audio duration (rough: assume ~100KB per minute for compressed audio)
    estimated_duration_seconds = max(1, (file_size / 100_000) * 60)

    # Track which provider we used
    used_provider = None
    used_provider_key = None
    last_error = None

    # Try each provider in order
    for provider_id in WHISPER_FALLBACK_ORDER:
        provider_config = WHISPER_PROVIDERS.get(provider_id)
        if not provider_config:
            continue

        # Get provider key if needed
        provider_key = None
        decrypted_key = None
        if provider_config["auth_type"]:
            provider_key = await get_provider_key(group_id, provider_id, db)
            if not provider_key:
                # No key for this provider, try next
                continue
            decrypted_key = decrypt_api_key(provider_key.encrypted_key)

        # Build the request
        url = f"{provider_config['base_url']}/audio/transcriptions"
        headers = {}
        if decrypted_key:
            headers["Authorization"] = f"Bearer {decrypted_key}"

        # Build form data - use provider-specific model
        form_data = {
            "model": provider_config.get("model", model),
        }
        if language:
            form_data["language"] = language
        if prompt:
            form_data["prompt"] = prompt
        form_data["response_format"] = response_format
        form_data["temperature"] = str(temperature)

        # Reset file position for retry
        files = {"file": (file.filename, audio_content, file.content_type or "audio/webm")}

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    data=form_data,
                    files=files,
                )

                if response.status_code == 200:
                    used_provider = provider_id
                    used_provider_key = provider_key

                    # Calculate latency
                    latency_ms = int((time.time() - start_time) * 1000)

                    # Log usage
                    await log_whisper_usage(
                        db=db,
                        api_key_id=api_key_obj.id,
                        provider_key_id=provider_key.id if provider_key else None,
                        provider=provider_id,
                        model=form_data["model"],
                        audio_duration_seconds=estimated_duration_seconds,
                        latency_ms=latency_ms,
                        app_id=request.headers.get("X-App-Id"),
                    )

                    # Return the response based on format
                    if response_format == "json" or response_format == "verbose_json":
                        result = response.json()
                        result["_artemis"] = {
                            "provider": provider_id,
                            "latency_ms": latency_ms,
                        }
                        return result
                    else:
                        # For text, srt, vtt formats - return as plain text
                        return PlainTextResponse(
                            content=response.text,
                            media_type="text/plain",
                            headers={"X-Artemis-Provider": provider_id, "X-Artemis-Latency-Ms": str(latency_ms)},
                        )
                else:
                    last_error = f"{provider_id}: HTTP {response.status_code} - {response.text[:200]}"
                    continue

        except httpx.TimeoutException:
            last_error = f"{provider_id}: Timeout"
            continue
        except httpx.ConnectError:
            last_error = f"{provider_id}: Connection failed"
            continue
        except Exception as e:
            last_error = f"{provider_id}: {str(e)}"
            continue

    # All providers failed
    return make_error_response(
        f"All Whisper providers failed. Last error: {last_error}",
        503,
    )


@router.get("/v1/audio/providers")
async def list_whisper_providers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List available Whisper providers and their status."""
    auth_header = request.headers.get("Authorization", "")
    api_key_obj, error = await validate_api_key(auth_header, db)
    if error:
        return make_error_response(error, 401)

    if not api_key_obj.group_id:
        return make_error_response("API key has no group assigned", 400)

    providers = []
    for provider_id, config in WHISPER_PROVIDERS.items():
        provider_info = {
            "id": provider_id,
            "name": config["name"],
            "requires_key": config["auth_type"] is not None,
        }

        # Check if we have a key for this provider
        if config["auth_type"]:
            key = await get_provider_key(api_key_obj.group_id, provider_id, db)
            provider_info["has_key"] = key is not None
        else:
            provider_info["has_key"] = True  # Self-hosted doesn't need a key

        providers.append(provider_info)

    return {"providers": providers, "fallback_order": WHISPER_FALLBACK_ORDER}
