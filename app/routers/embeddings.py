"""
Embeddings router.

Generates vector embeddings using local Ollama or cloud providers.
Uses the same API key validation and usage tracking as other Artemis endpoints.
"""
import hashlib
import time
from datetime import datetime, timezone
from typing import Optional, List, Union

import httpx
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.auth import decrypt_api_key
from app.models import APIKey, ProviderKey, ProviderAccount, UsageLog

router = APIRouter()

# Embedding provider configuration
EMBEDDING_PROVIDERS = {
    "ollama": {
        "name": "Local Ollama",
        "base_url": "http://localhost:11434",
        "auth_type": None,  # No auth needed for local
        "model": "nomic-embed-text",
        "dimensions": 768,
    },
    "openai": {
        "name": "OpenAI Embeddings",
        "base_url": "https://api.openai.com/v1",
        "auth_type": "bearer",
        "model": "text-embedding-3-small",
        "dimensions": 1536,
    },
    "voyage": {
        "name": "Voyage AI",
        "base_url": "https://api.voyageai.com/v1",
        "auth_type": "bearer",
        "model": "voyage-3",
        "dimensions": 1024,
    },
}

# Provider fallback order - local first, then cloud
EMBEDDING_FALLBACK_ORDER = ["ollama", "openai", "voyage"]


class EmbedRequest(BaseModel):
    """OpenAI-compatible embedding request."""
    input: Union[str, List[str]]
    model: str = "nomic-embed-text"
    encoding_format: str = "float"
    dimensions: Optional[int] = None
    # Artemis-specific
    task: str = "search_document"  # For nomic-embed-text task prefixes


class EmbedResponse(BaseModel):
    """OpenAI-compatible embedding response."""
    object: str = "list"
    data: List[dict]
    model: str
    usage: dict


async def validate_api_key(
    api_key: str,
    db: AsyncSession,
) -> tuple[Optional[APIKey], Optional[str]]:
    """Validate an Artemis API key and return the key object."""
    if not api_key:
        return None, "Missing API key"

    if api_key.startswith("Bearer "):
        api_key = api_key[7:]

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


async def get_provider_key(
    group_id: str,
    provider_id: str,
    db: AsyncSession,
) -> Optional[ProviderKey]:
    """Get the default provider key for a provider in a group."""
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


async def log_embedding_usage(
    db: AsyncSession,
    api_key_id: str,
    provider_key_id: Optional[str],
    provider: str,
    model: str,
    input_tokens: int,
    latency_ms: int,
    dimensions: int,
    app_id: Optional[str] = None,
):
    """Log embedding usage."""
    usage_log = UsageLog(
        api_key_id=api_key_id,
        provider_key_id=provider_key_id,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=0,
        latency_ms=latency_ms,
        app_id=app_id,
        request_metadata={
            "type": "embedding",
            "dimensions": dimensions,
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


async def embed_with_ollama(
    texts: List[str],
    model: str,
    task: str,
    base_url: str,
) -> tuple[Optional[List[List[float]]], Optional[str]]:
    """Generate embeddings using local Ollama."""
    embeddings = []

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for text in texts:
                # nomic-embed-text expects task prefixes
                prefixed_text = f"{task}: {text}"

                response = await client.post(
                    f"{base_url}/api/embeddings",
                    json={"model": model, "prompt": prefixed_text},
                )

                if response.status_code != 200:
                    return None, f"Ollama error: {response.status_code}"

                data = response.json()
                embeddings.append(data["embedding"])

        return embeddings, None
    except httpx.ConnectError:
        return None, "Ollama not available"
    except Exception as e:
        return None, str(e)


async def embed_with_openai(
    texts: List[str],
    model: str,
    api_key: str,
    base_url: str,
    dimensions: Optional[int] = None,
) -> tuple[Optional[List[List[float]]], Optional[str]]:
    """Generate embeddings using OpenAI API."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            payload = {
                "input": texts,
                "model": model,
            }
            if dimensions:
                payload["dimensions"] = dimensions

            response = await client.post(
                f"{base_url}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )

            if response.status_code != 200:
                return None, f"OpenAI error: {response.status_code} - {response.text[:200]}"

            data = response.json()
            embeddings = [item["embedding"] for item in data["data"]]
            return embeddings, None
    except Exception as e:
        return None, str(e)


@router.post("/v1/embeddings")
async def create_embeddings(
    request: Request,
    body: EmbedRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create embeddings for text.

    Compatible with OpenAI's /v1/embeddings endpoint.
    Tries providers in order: local Ollama → OpenAI → Voyage.
    """
    start_time = time.time()

    # Get API key from header
    auth_header = request.headers.get("Authorization", "")
    api_key_obj, error = await validate_api_key(auth_header, db)
    if error:
        return make_error_response(error, 401)

    if not api_key_obj.group_id:
        return make_error_response("API key has no group assigned", 400)

    group_id = api_key_obj.group_id

    # Normalize input to list
    texts = [body.input] if isinstance(body.input, str) else body.input

    # Estimate tokens (rough: ~4 chars per token)
    total_chars = sum(len(t) for t in texts)
    estimated_tokens = total_chars // 4

    # Track results
    embeddings = None
    used_provider = None
    used_provider_key = None
    last_error = None
    dimensions = 0

    # Try each provider
    for provider_id in EMBEDDING_FALLBACK_ORDER:
        provider_config = EMBEDDING_PROVIDERS.get(provider_id)
        if not provider_config:
            continue

        # Get provider key if needed
        provider_key = None
        decrypted_key = None
        if provider_config["auth_type"]:
            provider_key = await get_provider_key(group_id, provider_id, db)
            if not provider_key:
                continue
            decrypted_key = decrypt_api_key(provider_key.encrypted_key)

        # Generate embeddings based on provider
        if provider_id == "ollama":
            embeddings, error = await embed_with_ollama(
                texts=texts,
                model=provider_config["model"],
                task=body.task,
                base_url=provider_config["base_url"],
            )
        else:
            embeddings, error = await embed_with_openai(
                texts=texts,
                model=provider_config["model"],
                api_key=decrypted_key,
                base_url=provider_config["base_url"],
                dimensions=body.dimensions,
            )

        if embeddings:
            used_provider = provider_id
            used_provider_key = provider_key
            dimensions = len(embeddings[0]) if embeddings else 0
            break
        else:
            last_error = f"{provider_id}: {error}"

    if not embeddings:
        return make_error_response(
            f"All embedding providers failed. Last error: {last_error}",
            503,
        )

    # Calculate latency
    latency_ms = int((time.time() - start_time) * 1000)

    # Log usage
    await log_embedding_usage(
        db=db,
        api_key_id=api_key_obj.id,
        provider_key_id=used_provider_key.id if used_provider_key else None,
        provider=used_provider,
        model=EMBEDDING_PROVIDERS[used_provider]["model"],
        input_tokens=estimated_tokens,
        latency_ms=latency_ms,
        dimensions=dimensions,
        app_id=request.headers.get("X-App-Id"),
    )

    # Build OpenAI-compatible response
    data = [
        {
            "object": "embedding",
            "index": i,
            "embedding": emb,
        }
        for i, emb in enumerate(embeddings)
    ]

    return {
        "object": "list",
        "data": data,
        "model": EMBEDDING_PROVIDERS[used_provider]["model"],
        "usage": {
            "prompt_tokens": estimated_tokens,
            "total_tokens": estimated_tokens,
        },
        "_artemis": {
            "provider": used_provider,
            "dimensions": dimensions,
            "latency_ms": latency_ms,
        },
    }


@router.get("/v1/embeddings/providers")
async def list_embedding_providers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List available embedding providers and their status."""
    auth_header = request.headers.get("Authorization", "")
    api_key_obj, error = await validate_api_key(auth_header, db)
    if error:
        return make_error_response(error, 401)

    if not api_key_obj.group_id:
        return make_error_response("API key has no group assigned", 400)

    providers = []
    for provider_id, config in EMBEDDING_PROVIDERS.items():
        provider_info = {
            "id": provider_id,
            "name": config["name"],
            "model": config["model"],
            "dimensions": config["dimensions"],
            "requires_key": config["auth_type"] is not None,
        }

        if config["auth_type"]:
            key = await get_provider_key(api_key_obj.group_id, provider_id, db)
            provider_info["has_key"] = key is not None
        else:
            provider_info["has_key"] = True

        providers.append(provider_info)

    return {"providers": providers, "fallback_order": EMBEDDING_FALLBACK_ORDER}


@router.get("/v1/embeddings/health")
async def embedding_health():
    """Check if local Ollama is available."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                embed_models = [m["name"] for m in models if "embed" in m["name"].lower()]
                return {
                    "status": "healthy",
                    "ollama": "connected",
                    "embedding_models": embed_models,
                }
    except Exception as e:
        pass

    return {
        "status": "degraded",
        "ollama": "unreachable",
        "message": "Local Ollama unavailable, will fallback to cloud providers",
    }
