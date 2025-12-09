"""Tests for API key revocation."""
import pytest
import re


class TestAPIKeyRevocation:
    """Test API key revocation scenarios."""

    @pytest.mark.asyncio
    async def test_revoke_api_key(self, authenticated_client):
        """Revoking an API key marks it as revoked."""
        # Create a key
        await authenticated_client.post(
            "/api-keys",
            data={"name": "To Revoke"},
            follow_redirects=True,
        )

        # Get the key ID
        page = await authenticated_client.get("/api-keys")
        match = re.search(r'/api-keys/([a-f0-9-]+)/revoke', page.text)
        assert match is not None
        key_id = match.group(1)

        # Revoke it
        response = await authenticated_client.post(
            f"/api-keys/{key_id}/revoke",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Revoked" in response.text

    @pytest.mark.asyncio
    async def test_revoked_key_still_shown(self, authenticated_client):
        """Revoked keys are still visible in the list."""
        # Create and revoke a key
        await authenticated_client.post(
            "/api-keys",
            data={"name": "Visible After Revoke"},
            follow_redirects=True,
        )

        page = await authenticated_client.get("/api-keys")
        match = re.search(r'/api-keys/([a-f0-9-]+)/revoke', page.text)
        key_id = match.group(1)

        await authenticated_client.post(
            f"/api-keys/{key_id}/revoke",
            follow_redirects=True,
        )

        # Check key is still visible
        page = await authenticated_client.get("/api-keys")
        assert "Visible After Revoke" in page.text
        assert "Revoked" in page.text

    @pytest.mark.asyncio
    async def test_revoked_key_no_revoke_button(self, authenticated_client):
        """Revoked keys don't show the revoke button."""
        # Create and revoke a key
        await authenticated_client.post(
            "/api-keys",
            data={"name": "No Button Test"},
            follow_redirects=True,
        )

        page = await authenticated_client.get("/api-keys")
        match = re.search(r'/api-keys/([a-f0-9-]+)/revoke', page.text)
        key_id = match.group(1)

        await authenticated_client.post(
            f"/api-keys/{key_id}/revoke",
            follow_redirects=True,
        )

        # The revoke action for this specific key should no longer be present
        page = await authenticated_client.get("/api-keys")
        assert f"/api-keys/{key_id}/revoke" not in page.text

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self, authenticated_client):
        """Revoking a nonexistent key doesn't crash."""
        response = await authenticated_client.post(
            "/api-keys/nonexistent-uuid/revoke",
            follow_redirects=False,
        )
        # Should redirect back to api-keys
        assert response.status_code == 303
        assert response.headers.get("location") == "/api-keys"

    @pytest.mark.asyncio
    async def test_revoke_other_users_key(self, client, test_db):
        """Cannot revoke another user's API key."""
        # Register first user and create a key
        await client.post(
            "/register",
            data={"email": "user1@example.com", "password": "password123"},
            follow_redirects=False,
        )
        await client.post(
            "/api-keys",
            data={"name": "User 1 Key"},
            follow_redirects=True,
        )

        page = await client.get("/api-keys")
        match = re.search(r'/api-keys/([a-f0-9-]+)/revoke', page.text)
        user1_key_id = match.group(1)

        # Logout
        await client.get("/logout", follow_redirects=False)
        client.cookies.clear()

        # Register second user
        response = await client.post(
            "/register",
            data={"email": "user2@example.com", "password": "password456"},
            follow_redirects=False,
        )
        client.cookies = response.cookies

        # Try to revoke user1's key
        await client.post(
            f"/api-keys/{user1_key_id}/revoke",
            follow_redirects=True,
        )

        # Login as user1 and verify key is NOT revoked
        await client.get("/logout", follow_redirects=False)
        client.cookies.clear()
        response = await client.post(
            "/login",
            data={"email": "user1@example.com", "password": "password123"},
            follow_redirects=False,
        )
        client.cookies = response.cookies

        page = await client.get("/api-keys")
        # Key should still be active (revoke button should be present)
        assert f"/api-keys/{user1_key_id}/revoke" in page.text

    @pytest.mark.asyncio
    async def test_revoke_requires_auth(self, client):
        """Revoking a key requires authentication."""
        response = await client.post(
            "/api-keys/any-uuid/revoke",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers.get("location") == "/login"
