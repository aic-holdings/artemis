import pytest
import asyncio
import os
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Disable localhost mode for tests BEFORE importing app
os.environ["LOCALHOST_MODE"] = "false"

from app.main import app
from app.database import Base, get_db
from app.config import settings

# Ensure localhost mode is disabled at runtime as well
settings.LOCALHOST_MODE = False


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db():
    """Create a fresh test database for each test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    yield async_session

    app.dependency_overrides.clear()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def client(test_db):
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def authenticated_client(client, test_db):
    """Create an authenticated test client with organization and group."""
    # Register a user
    response = await client.post(
        "/register",
        data={"email": "testuser@example.com", "password": "testpassword123"},
        follow_redirects=False,
    )

    # Get session cookie
    cookies = response.cookies
    client.cookies = cookies

    # Create organization and group for the test user
    # This is needed because provider keys now require a group context
    async with test_db() as session:
        from sqlalchemy import select
        from app.models import User, Organization, Group, GroupMember, Provider

        # Get the user
        result = await session.execute(
            select(User).where(User.email == "testuser@example.com")
        )
        user = result.scalar_one()

        # Create organization
        org = Organization(name="Test Organization", owner_id=user.id)
        session.add(org)
        await session.commit()
        await session.refresh(org)

        # Create default group
        group = Group(
            organization_id=org.id,
            name="Default",
            is_default=True,
            created_by_id=user.id
        )
        session.add(group)
        await session.commit()
        await session.refresh(group)

        # Add user as group member (admin)
        member = GroupMember(
            group_id=group.id,
            user_id=user.id,
            role="admin"
        )
        session.add(member)

        # Update user's organization and settings
        user.organization_id = org.id
        user.settings = {
            "last_org_id": org.id,
            "last_group_id": group.id
        }
        await session.commit()

        # Create provider records
        providers = [
            Provider(id="openai", name="OpenAI"),
            Provider(id="anthropic", name="Anthropic"),
            Provider(id="google", name="Google"),
            Provider(id="perplexity", name="Perplexity"),
            Provider(id="openrouter", name="OpenRouter"),
            Provider(id="v0", name="v0 (Vercel)"),
        ]
        for provider in providers:
            # Check if provider already exists
            existing = await session.execute(
                select(Provider).where(Provider.id == provider.id)
            )
            if not existing.scalar_one_or_none():
                session.add(provider)
        await session.commit()

    yield client
