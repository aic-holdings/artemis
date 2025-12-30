import os
from dotenv import load_dotenv

load_dotenv()


def _require_env(key: str) -> str:
    """Get required environment variable or raise error."""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"{key} environment variable is required")
    return value


class Settings:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    DATABASE_URL: str = _require_env("DATABASE_URL")
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "dev-encryption-key-32bytes!")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRATION_HOURS: int = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

    # Server settings
    DEFAULT_PORT: int = int(os.getenv("PORT", "8767"))
    DEFAULT_HOST: str = os.getenv("HOST", "127.0.0.1")

    # Localhost mode - auto-login without authentication
    LOCALHOST_MODE: bool = os.getenv("LOCALHOST_MODE", "true").lower() == "true"
    LOCALHOST_USER_EMAIL: str = os.getenv("LOCALHOST_USER_EMAIL", "dshanklin@aicholdings.com")

    # Jetta SSO settings
    SSO_ENABLED: bool = os.getenv("SSO_ENABLED", "true").lower() == "true"
    JETTA_SSO_URL: str = os.getenv("JETTA_SSO_URL", "https://login.jettaintelligence.com")
    SSO_COOKIE_NAME: str = "jetta_token"
    # Artemis URL for SSO callback redirect
    ARTEMIS_URL: str = os.getenv("ARTEMIS_URL", "https://artemis.jettaintelligence.com")

    # Master API key for admin operations (creating service accounts, issuing keys)
    # This bypasses normal auth and should be kept secure
    MASTER_API_KEY: str = os.getenv("MASTER_API_KEY", "")

    # Provider base URLs
    PROVIDER_URLS = {
        "openai": "https://api.openai.com",
        "anthropic": "https://api.anthropic.com",
        "google": "https://generativelanguage.googleapis.com",
        "perplexity": "https://api.perplexity.ai",
        "openrouter": "https://openrouter.ai/api/v1",
    }


settings = Settings()
