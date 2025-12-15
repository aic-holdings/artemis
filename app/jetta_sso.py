"""
Jetta SSO Integration for Artemis

Handles SSO authentication via Jetta's centralized auth service.
Supports both cookie-based (popup flow) and token-based authentication.
"""

from typing import Optional
import httpx
from fastapi import Request

from app.config import settings


class JettaSSO:
    """Client for Jetta SSO authentication."""

    def __init__(
        self,
        sso_url: str = None,
        cookie_name: str = None,
    ):
        self.sso_url = sso_url or settings.JETTA_SSO_URL
        self.cookie_name = cookie_name or settings.SSO_COOKIE_NAME
        self._http_client = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy-initialized async HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    def login_url(self, redirect_uri: str = None) -> str:
        """
        Get the URL to redirect users to for SSO login.

        Args:
            redirect_uri: Where to redirect after successful login

        Returns:
            The Jetta SSO login URL
        """
        url = f"{self.sso_url}/login"
        if redirect_uri:
            url += f"?redirect_uri={redirect_uri}"
        return url

    def logout_url(self, redirect_uri: str = None) -> str:
        """Get the URL to redirect users to for SSO logout."""
        url = f"{self.sso_url}/logout"
        if redirect_uri:
            url += f"?redirect_uri={redirect_uri}"
        return url

    async def verify_token(self, token: str) -> Optional[dict]:
        """
        Verify a token with Jetta SSO and get user info.

        Args:
            token: The JWT access token from jetta_token cookie

        Returns:
            User dict if valid, None otherwise.
            User dict contains: id, email, display_name, avatar_url, created_at
        """
        try:
            response = await self.http_client.post(
                f"{self.sso_url}/api/verify",
                json={"token": token},
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("valid"):
                    return data.get("user")
        except Exception as e:
            print(f"Jetta SSO verify error: {e}")
        return None

    async def get_user_from_cookie(self, request: Request) -> Optional[dict]:
        """
        Get user from the Jetta SSO cookie (jetta_token).

        Args:
            request: FastAPI Request object

        Returns:
            User dict if authenticated, None otherwise
        """
        token = request.cookies.get(self.cookie_name)
        if not token:
            return None
        return await self.verify_token(token)

    async def get_user_from_header(self, request: Request) -> Optional[dict]:
        """
        Get user from Authorization header.

        Args:
            request: FastAPI Request object

        Returns:
            User dict if authenticated, None otherwise
        """
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:]
        return await self.verify_token(token)

    async def get_current_user(self, request: Request) -> Optional[dict]:
        """
        Get current user from cookie or header.
        Tries cookie first (for browser sessions), then Authorization header.

        Args:
            request: FastAPI Request object

        Returns:
            User dict if authenticated, None otherwise
        """
        # Try cookie first (browser sessions use this)
        user = await self.get_user_from_cookie(request)
        if user:
            return user
        # Fall back to header (API calls)
        return await self.get_user_from_header(request)

    async def close(self):
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


# Singleton instance for the app
_sso_client: Optional[JettaSSO] = None


def get_sso_client() -> JettaSSO:
    """Get the singleton JettaSSO client instance."""
    global _sso_client
    if _sso_client is None:
        _sso_client = JettaSSO()
    return _sso_client


async def verify_sso_token(token: str) -> Optional[dict]:
    """Convenience function to verify a token."""
    return await get_sso_client().verify_token(token)


async def get_sso_user(request: Request) -> Optional[dict]:
    """Convenience function to get user from request."""
    return await get_sso_client().get_current_user(request)
