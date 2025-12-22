"""
Encryption Key Validator

Validates that the current ENCRYPTION_KEY can decrypt existing provider keys.
This prevents silent failures when ENCRYPTION_KEY is changed without migration.
"""

from typing import Dict, Any
from sqlalchemy import select, text
from cryptography.fernet import InvalidToken

from app.database import async_session_maker
from app.auth import decrypt_api_key
from app.models import ProviderKey


async def validate_encryption_key() -> Dict[str, Any]:
    """
    Validate that the current ENCRYPTION_KEY can decrypt existing provider keys.

    Returns:
        Dict with status and details:
        - status: "ok" | "warning" | "error"
        - message: Human-readable status
        - total_keys: Number of provider keys in database
        - decryptable_keys: Number that can be decrypted
        - affected_count: Number that cannot be decrypted (if error)
        - error: Error message (if error)
    """
    try:
        async with async_session_maker() as session:
            # Get all provider keys
            result = await session.execute(select(ProviderKey))
            keys = result.scalars().all()

            total_keys = len(keys)

            if total_keys == 0:
                return {
                    "status": "ok",
                    "message": "No provider keys configured",
                    "total_keys": 0,
                    "decryptable_keys": 0,
                }

            # Try to decrypt each key
            decryptable = 0
            failed_keys = []

            for key in keys:
                try:
                    # Attempt decryption
                    decrypt_api_key(key.encrypted_key)
                    decryptable += 1
                except InvalidToken:
                    failed_keys.append({
                        "id": str(key.id),
                        "name": key.name,
                        "suffix": key.key_suffix,
                    })
                except Exception as e:
                    failed_keys.append({
                        "id": str(key.id),
                        "name": key.name,
                        "error": str(e),
                    })

            if len(failed_keys) == 0:
                return {
                    "status": "ok",
                    "message": f"All {total_keys} provider keys can be decrypted",
                    "total_keys": total_keys,
                    "decryptable_keys": decryptable,
                }
            elif decryptable > 0:
                # Some keys work, some don't - weird state
                return {
                    "status": "warning",
                    "message": f"{len(failed_keys)} of {total_keys} keys cannot be decrypted",
                    "total_keys": total_keys,
                    "decryptable_keys": decryptable,
                    "affected_count": len(failed_keys),
                    "failed_keys": failed_keys,
                }
            else:
                # All keys fail - ENCRYPTION_KEY mismatch
                return {
                    "status": "error",
                    "error": "ENCRYPTION_KEY mismatch - cannot decrypt any provider keys",
                    "total_keys": total_keys,
                    "decryptable_keys": 0,
                    "affected_count": len(failed_keys),
                    "failed_keys": failed_keys,
                }

    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to validate encryption: {str(e)}",
            "total_keys": 0,
            "decryptable_keys": 0,
        }


async def get_encryption_health() -> Dict[str, Any]:
    """
    Get current encryption health status for health check endpoint.
    Lighter weight than full validation - just checks if we CAN decrypt.
    """
    try:
        async with async_session_maker() as session:
            # Just check if any provider key exists and can be decrypted
            result = await session.execute(
                select(ProviderKey).limit(1)
            )
            key = result.scalar_one_or_none()

            if key is None:
                return {"status": "ok", "message": "No provider keys configured"}

            try:
                decrypt_api_key(key.encrypted_key)
                return {"status": "ok", "message": "Encryption key valid"}
            except InvalidToken:
                return {
                    "status": "error",
                    "message": "ENCRYPTION_KEY mismatch - cannot decrypt provider keys"
                }
    except Exception as e:
        return {"status": "error", "message": str(e)}
