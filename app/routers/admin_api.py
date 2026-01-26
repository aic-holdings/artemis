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
from app.models import User, Organization, Group, APIKey, Provider, ProviderAccount, ProviderKey
from app.config import settings
from app.auth import generate_api_key, hash_password, encrypt_api_key


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


# =============================================================================
# Provider Key Management (Admin)
# =============================================================================


class AddProviderKeyRequest(BaseModel):
    """Request to add a provider API key."""
    provider_id: str  # e.g., "openai", "v0"
    api_key: str  # The actual provider API key
    name: str = "Default"
    service_account_name: Optional[str] = None  # If None, uses first available group


class AddProviderKeyResponse(BaseModel):
    """Response after adding a provider key."""
    provider_id: str
    account_id: str
    key_id: str
    key_suffix: str
    group_id: str
    message: str


@router.post("/provider-keys", response_model=AddProviderKeyResponse)
async def add_provider_key(
    body: AddProviderKeyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Add a provider API key (e.g., OpenAI, Anthropic, v0).

    This allows AI agents to configure provider keys programmatically.

    **Request:**
    ```
    POST /api/v1/admin/provider-keys
    Authorization: Bearer <MASTER_API_KEY>
    Content-Type: application/json

    {
        "provider_id": "v0",
        "api_key": "v1:xxx...",
        "name": "v0 API Key",
        "service_account_name": "janus"  // optional
    }
    ```
    """
    await verify_master_key(request)

    provider_id = body.provider_id.lower().strip()
    if not provider_id:
        raise HTTPException(status_code=400, detail="provider_id is required")

    # Verify provider exists
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        # Auto-create provider if it's a known one
        if provider_id in settings.PROVIDER_URLS:
            provider = Provider(
                id=provider_id,
                name=provider_id.title(),
                base_url=settings.PROVIDER_URLS[provider_id],
                is_active=True
            )
            db.add(provider)
            await db.flush()
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found and not in PROVIDER_URLS"
            )

    # Find group and user for key ownership
    group = None
    owner_user = None

    if body.service_account_name:
        # Use service account's group and user
        email = f"{body.service_account_name.lower()}@service.artemis.local"
        result = await db.execute(
            select(User).where(User.email == email, User.is_service_account == True)
        )
        owner_user = result.scalar_one_or_none()
        if not owner_user:
            raise HTTPException(
                status_code=404,
                detail=f"Service account '{body.service_account_name}' not found"
            )

        result = await db.execute(
            select(Group)
            .join(Organization, Group.organization_id == Organization.id)
            .where(Organization.owner_id == owner_user.id)
        )
        group = result.scalar_one_or_none()
    else:
        # Use first available group and its owner
        result = await db.execute(
            select(Group, Organization)
            .join(Organization, Group.organization_id == Organization.id)
            .limit(1)
        )
        row = result.first()
        if row:
            group, org = row
            # Get the organization owner as the key owner
            result = await db.execute(select(User).where(User.id == org.owner_id))
            owner_user = result.scalar_one_or_none()

    if not group or not owner_user:
        raise HTTPException(
            status_code=404,
            detail="No groups found. Create a service account first."
        )

    # Get or create provider account for this group
    result = await db.execute(
        select(ProviderAccount).where(
            ProviderAccount.group_id == group.id,
            ProviderAccount.provider_id == provider_id
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        account = ProviderAccount(
            group_id=group.id,
            provider_id=provider_id,
            name="Default"
        )
        db.add(account)
        await db.flush()

    # Check if key already exists with same suffix
    key_suffix = body.api_key[-4:] if len(body.api_key) >= 4 else body.api_key
    result = await db.execute(
        select(ProviderKey).where(
            ProviderKey.provider_account_id == account.id,
            ProviderKey.key_suffix == key_suffix
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Key ending in ****{key_suffix} already exists for {provider_id}"
        )

    # Add the key
    provider_key = ProviderKey(
        provider_account_id=account.id,
        user_id=owner_user.id,
        encrypted_key=encrypt_api_key(body.api_key),
        name=body.name,
        key_suffix=key_suffix,
        is_default=True,
        is_active=True
    )
    db.add(provider_key)
    await db.commit()

    return AddProviderKeyResponse(
        provider_id=provider_id,
        account_id=str(account.id),
        key_id=str(provider_key.id),
        key_suffix=key_suffix,
        group_id=str(group.id),
        message=f"Provider key added for {provider_id}"
    )


@router.get("/provider-keys")
async def list_provider_keys(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    List all provider keys (admin view).

    **Request:**
    ```
    GET /api/v1/admin/provider-keys
    Authorization: Bearer <MASTER_API_KEY>
    ```
    """
    await verify_master_key(request)

    result = await db.execute(
        select(ProviderKey, ProviderAccount, Group)
        .join(ProviderAccount, ProviderKey.provider_account_id == ProviderAccount.id)
        .join(Group, ProviderAccount.group_id == Group.id)
    )
    rows = result.all()

    return {
        "provider_keys": [
            {
                "id": str(pk.id),
                "provider_id": pa.provider_id,
                "name": pk.name,
                "key_suffix": pk.key_suffix,
                "is_active": pk.is_active,
                "is_default": pk.is_default,
                "group_name": g.name,
                "account_name": pa.name,
            }
            for pk, pa, g in rows
        ]
    }


@router.delete("/provider-keys/{key_id}")
async def delete_provider_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a provider key.

    **Request:**
    ```
    DELETE /api/v1/admin/provider-keys/{key_id}
    Authorization: Bearer <MASTER_API_KEY>
    ```
    """
    await verify_master_key(request)

    result = await db.execute(select(ProviderKey).where(ProviderKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="Provider key not found")

    await db.delete(key)
    await db.commit()

    return {"message": "Provider key deleted", "id": key_id}


# =============================================================================
# Platform Admin Management
# =============================================================================


class SetPlatformAdminRequest(BaseModel):
    """Request to set platform admin status for a user."""
    email: str
    is_platform_admin: bool = True


@router.post("/platform-admins")
async def set_platform_admin(
    body: SetPlatformAdminRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Set platform admin status for a user.

    Platform admins can see ALL organizations, groups, and usage data
    across the entire Artemis instance.

    **Request:**
    ```
    POST /api/v1/admin/platform-admins
    Authorization: Bearer <MASTER_API_KEY>
    Content-Type: application/json

    {"email": "admin@example.com", "is_platform_admin": true}
    ```
    """
    await verify_master_key(request)

    # Find user by email
    result = await db.execute(
        select(User).where(User.email == body.email)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{body.email}' not found")

    # Update platform admin status
    user.is_platform_admin = body.is_platform_admin
    await db.commit()

    return {
        "message": f"Platform admin status updated for {body.email}",
        "email": body.email,
        "is_platform_admin": body.is_platform_admin,
    }


@router.get("/platform-admins")
async def list_platform_admins(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    List all platform admins.

    **Request:**
    ```
    GET /api/v1/admin/platform-admins
    Authorization: Bearer <MASTER_API_KEY>
    ```
    """
    await verify_master_key(request)

    result = await db.execute(
        select(User).where(User.is_platform_admin == True)
    )
    admins = result.scalars().all()

    return {
        "platform_admins": [
            {
                "id": str(u.id),
                "email": u.email,
                "is_service_account": u.is_service_account,
            }
            for u in admins
        ]
    }


@router.get("/users")
async def list_all_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    List all users (for admin lookup).

    **Request:**
    ```
    GET /api/v1/admin/users
    Authorization: Bearer <MASTER_API_KEY>
    ```
    """
    await verify_master_key(request)

    result = await db.execute(
        select(User).order_by(User.email)
    )
    users = result.scalars().all()

    return {
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "is_service_account": u.is_service_account,
                "is_platform_admin": getattr(u, 'is_platform_admin', False),
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    }
