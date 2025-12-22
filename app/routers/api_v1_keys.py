"""
Programmatic API for key management.

Allows CLI tools and automated systems to create/manage API keys
and provider keys using an existing Artemis key for authentication.
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import APIKey, User
from app.services.api_key_service import APIKeyService
from app.services.provider_account_service import ProviderAccountService
from app.services.provider_key_service import ProviderKeyService


router = APIRouter(prefix="/api/v1", tags=["API Keys"])


class CreateKeyRequest(BaseModel):
    """Request body for creating a new API key."""
    name: str = "Default"


class CreateKeyResponse(BaseModel):
    """Response after creating an API key."""
    id: str
    name: str
    key: str  # Full key - only shown at creation
    key_prefix: str
    created_at: str


async def get_api_key_from_header(
    request: Request, db: AsyncSession = Depends(get_db)
) -> APIKey:
    """
    Validate Artemis API key from Authorization header.

    Returns the APIKey object if valid.
    """
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Use: Authorization: Bearer art_xxx"
        )

    api_key_value = auth_header[7:]  # Remove "Bearer "

    if not api_key_value.startswith("art_"):
        raise HTTPException(status_code=401, detail="Invalid API key format. Keys start with 'art_'")

    # Hash and lookup
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

    return api_key


@router.post("/keys", response_model=CreateKeyResponse)
async def create_key(
    body: CreateKeyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new API key programmatically.

    Authenticate with an existing Artemis key in the Authorization header.
    The new key will be created for the same user/group as the authenticating key.

    **Request:**
    ```
    POST /api/v1/keys
    Authorization: Bearer art_xxx
    Content-Type: application/json

    {"name": "My New Key"}
    ```

    **Response:**
    ```json
    {
        "id": "uuid",
        "name": "My New Key",
        "key": "art_full_key_here",
        "key_prefix": "art_xxxx",
        "created_at": "2025-01-01T00:00:00Z"
    }
    ```

    The full `key` is only returned at creation time. Store it securely.
    """
    # Validate the authenticating key
    auth_key = await get_api_key_from_header(request, db)

    api_key_service = APIKeyService(db)

    # Normalize name
    name = body.name.strip() or "Default"

    # Check for duplicate name in same scope
    if await api_key_service.name_exists(auth_key.user_id, name, auth_key.group_id):
        raise HTTPException(
            status_code=409,
            detail=f"A key named '{name}' already exists. Choose a different name."
        )

    # Create the new key in the same user/group scope as the auth key
    new_key, full_key = await api_key_service.create(
        user_id=auth_key.user_id,
        name=name,
        group_id=auth_key.group_id
    )

    return CreateKeyResponse(
        id=str(new_key.id),
        name=new_key.name,
        key=full_key,
        key_prefix=new_key.key_prefix,
        created_at=new_key.created_at.isoformat()
    )


@router.get("/keys")
async def list_keys(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    List all API keys for the authenticated user/group.

    Returns key metadata (not the actual keys).
    """
    auth_key = await get_api_key_from_header(request, db)

    api_key_service = APIKeyService(db)

    if auth_key.group_id:
        keys = await api_key_service.get_all_for_group(auth_key.group_id)
    else:
        keys = await api_key_service.get_all_for_user(auth_key.user_id, group_id=None)

    return {
        "keys": [
            {
                "id": str(k.id),
                "name": k.name,
                "key_prefix": k.key_prefix,
                "is_system": k.is_system,
                "created_at": k.created_at.isoformat(),
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
            }
            for k in keys
        ]
    }


@router.delete("/keys/{key_id}")
async def revoke_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke an API key.

    Cannot revoke system keys or the key used for authentication.
    """
    auth_key = await get_api_key_from_header(request, db)

    # Can't revoke your own auth key
    if str(auth_key.id) == key_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot revoke the key you're using for authentication"
        )

    api_key_service = APIKeyService(db)

    # Get the target key
    target_key = await api_key_service.get_by_id(
        key_id,
        user_id=auth_key.user_id,
        group_id=auth_key.group_id
    )

    if not target_key:
        raise HTTPException(status_code=404, detail="Key not found")

    if target_key.is_system:
        raise HTTPException(status_code=400, detail="Cannot revoke system keys")

    if target_key.revoked_at:
        raise HTTPException(status_code=400, detail="Key already revoked")

    target_key.revoked_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message": "Key revoked", "id": key_id}


# ============================================================================
# Provider Key Management API
# ============================================================================


class AddProviderKeyRequest(BaseModel):
    """Request body for adding a provider key."""
    api_key: str
    name: str = "Default"


@router.get("/providers")
async def list_provider_keys(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    List all provider keys for the authenticated group.

    **Request:**
    ```
    GET /api/v1/providers
    Authorization: Bearer art_xxx
    ```

    **Response:**
    ```json
    {
        "group_id": "uuid",
        "providers": {
            "openrouter": [
                {"id": "uuid", "name": "Default", "key_suffix": "3d3d", "is_default": true}
            ],
            "openai": [...]
        }
    }
    ```
    """
    auth_key = await get_api_key_from_header(request, db)

    if not auth_key.group_id:
        raise HTTPException(
            status_code=400,
            detail="API key is not associated with a group. Provider keys require group context."
        )

    provider_key_service = ProviderKeyService(db)
    keys = await provider_key_service.get_all_for_group(auth_key.group_id, include_account=True)

    # Organize by provider
    providers = {}
    for key in keys:
        provider_id = key.account.provider_id if key.account else "unknown"
        if provider_id not in providers:
            providers[provider_id] = []
        providers[provider_id].append({
            "id": str(key.id),
            "name": key.name,
            "key_suffix": key.key_suffix,
            "is_default": key.is_default,
            "is_active": key.is_active,
            "created_at": key.created_at.isoformat() if key.created_at else None,
        })

    return {
        "group_id": str(auth_key.group_id),
        "providers": providers,
    }


@router.post("/providers/{provider_id}/keys")
async def add_provider_key(
    provider_id: str,
    body: AddProviderKeyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Add a provider API key to the authenticated group.

    This creates a provider account (if needed) and adds the key to it.
    The key will be encrypted and stored securely.

    **Request:**
    ```
    POST /api/v1/providers/openrouter/keys
    Authorization: Bearer art_xxx
    Content-Type: application/json

    {"api_key": "sk-or-v1-xxx", "name": "Production Key"}
    ```

    **Response:**
    ```json
    {
        "id": "uuid",
        "name": "Production Key",
        "key_suffix": "xxxx",
        "provider_id": "openrouter",
        "is_default": true
    }
    ```
    """
    auth_key = await get_api_key_from_header(request, db)

    if not auth_key.group_id:
        raise HTTPException(
            status_code=400,
            detail="API key is not associated with a group. Provider keys require group context."
        )

    # Normalize provider ID
    provider_id = provider_id.lower().strip()

    # Valid providers
    valid_providers = ["openai", "anthropic", "google", "openrouter", "perplexity"]
    if provider_id not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {provider_id}. Valid providers: {', '.join(valid_providers)}"
        )

    provider_account_service = ProviderAccountService(db)
    provider_key_service = ProviderKeyService(db)

    # Get or create a default account for this provider
    account = await provider_account_service.get_or_create_default(
        group_id=str(auth_key.group_id),
        provider_id=provider_id,
        created_by_id=str(auth_key.user_id),
    )

    # Check for duplicate key name
    name = body.name.strip() or "Default"
    if await provider_key_service.name_exists(str(account.id), name):
        raise HTTPException(
            status_code=409,
            detail=f"A key named '{name}' already exists for {provider_id}. Choose a different name."
        )

    # Create the key
    provider_key = await provider_key_service.create(
        provider_account_id=str(account.id),
        user_id=str(auth_key.user_id),
        key=body.api_key,
        name=name,
    )

    return {
        "id": str(provider_key.id),
        "name": provider_key.name,
        "key_suffix": provider_key.key_suffix,
        "provider_id": provider_id,
        "is_default": provider_key.is_default,
    }


@router.delete("/providers/keys/{key_id}")
async def delete_provider_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a provider API key.

    **Request:**
    ```
    DELETE /api/v1/providers/keys/{key_id}
    Authorization: Bearer art_xxx
    ```
    """
    auth_key = await get_api_key_from_header(request, db)

    if not auth_key.group_id:
        raise HTTPException(
            status_code=400,
            detail="API key is not associated with a group."
        )

    provider_key_service = ProviderKeyService(db)

    # Get the key and verify it belongs to this group
    key = await provider_key_service.get_by_id(key_id, include_account=True)
    if not key or not key.account or str(key.account.group_id) != str(auth_key.group_id):
        raise HTTPException(status_code=404, detail="Provider key not found")

    await provider_key_service.delete(key_id, str(auth_key.user_id))

    return {"message": "Provider key deleted", "id": key_id}
