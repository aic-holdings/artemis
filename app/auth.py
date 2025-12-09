import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
import bcrypt
from cryptography.fernet import Fernet
import base64

from app.config import settings


def get_fernet():
    """Get Fernet instance for encrypting provider keys."""
    # Ensure key is 32 bytes, base64 encoded
    key = settings.ENCRYPTION_KEY.encode()
    if len(key) < 32:
        key = key.ljust(32, b"0")
    key = base64.urlsafe_b64encode(key[:32])
    return Fernet(key)


def encrypt_api_key(api_key: str) -> str:
    """Encrypt a provider API key for storage."""
    f = get_fernet()
    return f.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt a provider API key."""
    f = get_fernet()
    return f.decrypt(encrypted_key.encode()).decode()


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new Artemis API key.

    Returns:
        tuple: (full_key, key_hash, key_prefix)
    """
    # Generate a random key with art_ prefix
    random_part = secrets.token_urlsafe(32)
    full_key = f"art_{random_part}"

    # Hash for storage
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()

    # Prefix for display
    key_prefix = full_key[:12]  # "art_" + first 8 chars

    return full_key, key_hash, key_prefix


def verify_api_key(api_key: str, key_hash: str) -> bool:
    """Verify an API key against its hash."""
    computed_hash = hashlib.sha256(api_key.encode()).hexdigest()
    return secrets.compare_digest(computed_hash, key_hash)


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    active_org_id: Optional[str] = None,
) -> str:
    """Create a JWT access token.

    Args:
        data: Token payload (typically {"sub": user_id})
        expires_delta: Optional custom expiration
        active_org_id: Optional org ID to set as active context
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    to_encode.update({"exp": expire})
    if active_org_id:
        to_encode["org"] = active_org_id
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT access token."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None
