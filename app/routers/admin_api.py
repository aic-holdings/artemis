"""
Admin API for master key operations.

Allows programmatic management of Artemis using the MASTER_API_KEY.
This enables AI agents to:
1. Create service accounts for applications
2. Issue API keys for those accounts
3. Manage all aspects of Artemis without UI

Authentication: Bearer token with MASTER_API_KEY value
"""
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Organization, Group, APIKey
from app.config import settings
from app.auth import generate_api_key, hash_password


router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


class CreateServiceAccountRequest(BaseModel):
    """Request to create a service account."""
    name: str  # e.g., "speaches", "janus"
    description: Optional[str] = None


class CreateServiceAccountResponse(BaseModel):
    """Response after creating a service account."""
    service_account_id: str
    name: str
    api_key: str  # Full key - only shown at creation
    key_prefix: str
    group_id: str
    message: str


class IssueKeyRequest(BaseModel):
    """Request to issue an API key for a service account."""
    service_account_name: str
    key_name: str = "Default"


class IssueKeyResponse(BaseModel):
    """Response after issuing an API key."""
    id: str
    name: str
    api_key: str
    key_prefix: str
    service_account: str


async def verify_master_key(request: Request) -> bool:
    """Verify the master API key from Authorization header."""
    if not settings.MASTER_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Master API key not configured. Set MASTER_API_KEY environment variable."
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Use: Authorization: Bearer <MASTER_API_KEY>"
        )

    provided_key = auth_header[7:]
    if not secrets.compare_digest(provided_key, settings.MASTER_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid master API key")

    return True


@router.post("/service-accounts", response_model=CreateServiceAccountResponse)
async def create_service_account(
    body: CreateServiceAccountRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a service account for an application.

    Service accounts are machine identities that can access Artemis APIs.
    Each service account gets:
    - A dedicated user (is_service_account=True)
    - An organization for isolation
    - A default group
    - An initial API key

    **Request:**
    ```
    POST /api/v1/admin/service-accounts
    Authorization: Bearer <MASTER_API_KEY>
    Content-Type: application/json

    {"name": "speaches", "description": "Speech AI playground"}
    ```

    **Response:**
    ```json
    {
        "service_account_id": "uuid",
        "name": "speaches",
        "api_key": "art_xxx",
        "key_prefix": "art_xxxx",
        "group_id": "uuid",
        "message": "Service account created. Store the API key securely."
    }
    ```
    """
    await verify_master_key(request)

    name = body.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    # Check if service account already exists
    email = f"{name}@service.artemis.local"
    result = await db.execute(
        select(User).where(User.email == email)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Service account '{name}' already exists"
        )

    # Create user (service account)
    user = User(
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),  # Random password, never used
        is_service_account=True,
    )
    db.add(user)
    await db.flush()

    # Create organization for the service account
    org = Organization(
        name=f"{name} Service",
        owner_id=user.id,
    )
    db.add(org)
    await db.flush()

    # Create default group
    group = Group(
        name="Default",
        organization_id=org.id,
    )
    db.add(group)
    await db.flush()

    # Generate API key
    full_key, key_hash, key_prefix = generate_api_key()

    api_key = APIKey(
        user_id=user.id,
        group_id=group.id,
        name=f"{name}-primary",
        key_hash=key_hash,
        key_prefix=key_prefix,
        is_system=False,
    )
    db.add(api_key)
    await db.commit()

    return CreateServiceAccountResponse(
        service_account_id=str(user.id),
        name=name,
        api_key=full_key,
        key_prefix=key_prefix,
        group_id=str(group.id),
        message="Service account created. Store the API key securely - it won't be shown again.",
    )


@router.get("/service-accounts")
async def list_service_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    List all service accounts.

    **Request:**
    ```
    GET /api/v1/admin/service-accounts
    Authorization: Bearer <MASTER_API_KEY>
    ```
    """
    await verify_master_key(request)

    result = await db.execute(
        select(User).where(User.is_service_account == True)
    )
    accounts = result.scalars().all()

    return {
        "service_accounts": [
            {
                "id": str(u.id),
                "name": u.email.replace("@service.artemis.local", ""),
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in accounts
        ]
    }


@router.post("/keys", response_model=IssueKeyResponse)
async def issue_key(
    body: IssueKeyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Issue an API key for an existing service account.

    Use this to create additional keys for a service account,
    or to rotate keys.

    **Request:**
    ```
    POST /api/v1/admin/keys
    Authorization: Bearer <MASTER_API_KEY>
    Content-Type: application/json

    {"service_account_name": "speaches", "key_name": "Production"}
    ```
    """
    await verify_master_key(request)

    name = body.service_account_name.strip().lower()
    email = f"{name}@service.artemis.local"

    # Find service account
    result = await db.execute(
        select(User).where(User.email == email, User.is_service_account == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"Service account '{name}' not found"
        )

    # Find user's group (via their organization)
    result = await db.execute(
        select(Group)
        .join(Organization, Group.organization_id == Organization.id)
        .where(Organization.owner_id == user.id)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=500,
            detail="Service account has no group - data inconsistency"
        )

    # Generate new API key
    full_key, key_hash, key_prefix = generate_api_key()

    api_key = APIKey(
        user_id=user.id,
        group_id=group.id,
        name=body.key_name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        is_system=False,
    )
    db.add(api_key)
    await db.commit()

    return IssueKeyResponse(
        id=str(api_key.id),
        name=body.key_name,
        api_key=full_key,
        key_prefix=key_prefix,
        service_account=name,
    )


@router.get("/keys/{service_account_name}")
async def list_keys_for_service_account(
    service_account_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    List API keys for a service account.

    **Request:**
    ```
    GET /api/v1/admin/keys/speaches
    Authorization: Bearer <MASTER_API_KEY>
    ```
    """
    await verify_master_key(request)

    name = service_account_name.strip().lower()
    email = f"{name}@service.artemis.local"

    result = await db.execute(
        select(User).where(User.email == email, User.is_service_account == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"Service account '{name}' not found"
        )

    result = await db.execute(
        select(APIKey).where(APIKey.user_id == user.id)
    )
    keys = result.scalars().all()

    return {
        "service_account": name,
        "keys": [
            {
                "id": str(k.id),
                "name": k.name,
                "key_prefix": k.key_prefix,
                "created_at": k.created_at.isoformat() if k.created_at else None,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
            }
            for k in keys
        ],
    }


@router.delete("/keys/{key_id}")
async def revoke_key_admin(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke any API key (admin override).

    **Request:**
    ```
    DELETE /api/v1/admin/keys/{key_id}
    Authorization: Bearer <MASTER_API_KEY>
    ```
    """
    await verify_master_key(request)

    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="Key not found")

    if api_key.revoked_at:
        raise HTTPException(status_code=400, detail="Key already revoked")

    api_key.revoked_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message": "Key revoked", "id": key_id}
