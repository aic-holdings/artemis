"""Artemis CLI API client - mockable for testing."""
import json
import os
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# Config paths
DEFAULT_URL = "https://artemis.jettaintelligence.com"
CONFIG_DIR = Path.home() / ".artemis"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


class APIError(Exception):
    """API error with status code and details."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Error {status_code}: {detail}")


class ConfigError(Exception):
    """Configuration error (missing keys, etc)."""
    pass


class ConnectionError(Exception):
    """Connection error."""
    pass


def load_config() -> dict:
    """Load config from ~/.artemis/config.yaml."""
    if not CONFIG_FILE.exists():
        return {}
    config = {}
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and ":" in line:
                key, value = line.split(":", 1)
                config[key.strip()] = value.strip()
    return config


def save_config(config: dict):
    """Save config to ~/.artemis/config.yaml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        for key, value in config.items():
            f.write(f"{key}: {value}\n")
    CONFIG_FILE.chmod(0o600)


def get_url() -> str:
    """Get Artemis URL from env or config."""
    return os.environ.get("ARTEMIS_URL") or load_config().get("url") or DEFAULT_URL


def get_api_key() -> str:
    """Get API key from env or config.

    Raises:
        ConfigError: If no API key is configured
    """
    key = os.environ.get("ARTEMIS_API_KEY") or load_config().get("api_key")
    if not key:
        raise ConfigError("ARTEMIS_API_KEY not found. Set with env var or 'artemis config set api_key'")
    return key


def get_master_key() -> str:
    """Get master API key from env or config.

    Raises:
        ConfigError: If no master key is configured
    """
    key = os.environ.get("MASTER_API_KEY") or load_config().get("master_api_key")
    if not key:
        raise ConfigError("MASTER_API_KEY not found. Set with env var or 'artemis config set master_api_key'")
    return key


def api_request(
    method: str,
    endpoint: str,
    data: dict = None,
    use_master: bool = False,
    timeout: int = 30,
    base_url: str = None,
    api_key: str = None,
) -> dict:
    """Make API request to Artemis.

    Args:
        method: HTTP method (GET, POST, etc)
        endpoint: API endpoint (e.g., /api/v1/admin/service-accounts)
        data: Request body (will be JSON encoded)
        use_master: Use master key instead of regular API key
        timeout: Request timeout in seconds
        base_url: Override base URL (for testing)
        api_key: Override API key (for testing)

    Returns:
        Parsed JSON response

    Raises:
        APIError: On HTTP errors
        ConnectionError: On network errors
        ConfigError: If required keys not configured
    """
    url = f"{(base_url or get_url()).rstrip('/')}{endpoint}"

    if api_key:
        key = api_key
    elif use_master:
        key = get_master_key()
    else:
        key = get_api_key()

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        try:
            error = json.loads(e.read().decode())
            detail = error.get("detail", str(error))
        except:
            detail = f"HTTP {e.code}"
        raise APIError(e.code, detail)
    except URLError as e:
        raise ConnectionError(f"Connection error: {e.reason}")
