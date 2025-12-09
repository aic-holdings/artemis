"""Tests for User settings functionality."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class TestUserSettings:
    """Test User settings JSONB field."""

    @pytest.mark.asyncio
    async def test_get_setting_default(self, test_db):
        """get_setting returns default when setting doesn't exist."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            # Settings defaults to empty dict
            assert user.settings == {}
            assert user.get_setting("last_org_id") is None
            assert user.get_setting("theme", "light") == "light"

    @pytest.mark.asyncio
    async def test_set_setting_creates_dict(self, test_db):
        """set_setting creates settings dict if None."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            session.add(user)
            await session.commit()
            await session.refresh(user)

            # Set a setting
            user.set_setting("last_org_id", "org-123")
            await session.commit()
            await session.refresh(user)

            assert user.settings is not None
            assert user.settings["last_org_id"] == "org-123"

    @pytest.mark.asyncio
    async def test_get_setting_retrieves_value(self, test_db):
        """get_setting retrieves stored value."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            user.settings = {"theme": "dark", "last_org_id": "org-456"}
            session.add(user)
            await session.commit()
            await session.refresh(user)

            assert user.get_setting("theme") == "dark"
            assert user.get_setting("last_org_id") == "org-456"
            assert user.get_setting("nonexistent") is None

    @pytest.mark.asyncio
    async def test_set_setting_updates_existing(self, test_db):
        """set_setting updates existing setting."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            user.settings = {"theme": "dark"}
            session.add(user)
            await session.commit()
            await session.refresh(user)

            # Update existing setting
            user.set_setting("theme", "light")
            await session.commit()
            await session.refresh(user)

            assert user.get_setting("theme") == "light"

    @pytest.mark.asyncio
    async def test_set_setting_adds_new(self, test_db):
        """set_setting adds new setting to existing dict."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            user.settings = {"theme": "dark"}
            session.add(user)
            await session.commit()
            await session.refresh(user)

            # Add new setting
            user.set_setting("last_org_id", "org-789")
            await session.commit()
            await session.refresh(user)

            assert user.get_setting("theme") == "dark"
            assert user.get_setting("last_org_id") == "org-789"

    @pytest.mark.asyncio
    async def test_set_setting_none_value(self, test_db):
        """set_setting can store None to clear a setting."""
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            user.settings = {"last_org_id": "org-123"}
            session.add(user)
            await session.commit()
            await session.refresh(user)

            # Set to None
            user.set_setting("last_org_id", None)
            await session.commit()
            await session.refresh(user)

            # Value should be None (explicitly stored)
            assert user.settings.get("last_org_id") is None

    @pytest.mark.asyncio
    async def test_settings_persisted_across_sessions(self, test_db):
        """Settings persist across database sessions."""
        user_id = None

        # First session: create user and set settings
        async with test_db() as session:
            user = User(email="test@example.com", password_hash="hash123")
            user.set_setting("last_org_id", "org-persist")
            user.set_setting("theme", "dark")
            session.add(user)
            await session.commit()
            await session.refresh(user)
            user_id = user.id

        # Second session: verify settings persisted
        async with test_db() as session:
            from sqlalchemy import select
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one()

            assert user.get_setting("last_org_id") == "org-persist"
            assert user.get_setting("theme") == "dark"
