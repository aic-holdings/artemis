#!/usr/bin/env python3
"""
Artemis CLI - Programmatic management for Artemis AI Management Platform.

Commands:
    # Service Account Management (requires MASTER_API_KEY)
    artemis-cli.py admin create-account NAME [--description DESC]
    artemis-cli.py admin list-accounts
    artemis-cli.py admin issue-key ACCOUNT_NAME [--name KEY_NAME]
    artemis-cli.py admin list-keys ACCOUNT_NAME

    # Provider Key Management (requires MASTER_API_KEY)
    artemis-cli.py admin add-provider PROVIDER_ID --key API_KEY [--name NAME] [--account ACCOUNT]
    artemis-cli.py admin list-providers

    # User Key Management (requires ARTEMIS_API_KEY)
    artemis-cli.py keys list
    artemis-cli.py keys create --name NAME
    artemis-cli.py keys revoke KEY_ID

    # Embeddings (requires ARTEMIS_API_KEY)
    artemis-cli.py embeddings health
    artemis-cli.py embeddings test "text to embed"
    artemis-cli.py embeddings providers

    # Health
    artemis-cli.py health

Configuration:
    Keys are loaded in order of precedence:
    1. Environment variables (MASTER_API_KEY, ARTEMIS_API_KEY, ARTEMIS_URL)
    2. Config file (~/.artemis/config.yaml)

    Config file format (~/.artemis/config.yaml):
        master_api_key: artemis_master_xxx
        api_key: art_xxx
        url: https://artemis.jettaintelligence.com

    # Initialize config
    artemis-cli.py config init
    artemis-cli.py config set api_key art_xxx
    artemis-cli.py config set master_api_key artemis_master_xxx
    artemis-cli.py config show

Examples:
    # Bootstrap: Create service account and add OpenRouter key
    export MASTER_API_KEY=your_master_key
    ./artemis-cli.py admin create-account taskr --description "Taskr embedding service"
    ./artemis-cli.py admin add-provider openrouter --key sk-or-v1-xxx --account taskr

    # Use the generated key
    export ARTEMIS_API_KEY=art_generated_key
    ./artemis-cli.py embeddings test "Hello world"
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


DEFAULT_ARTEMIS_URL = "https://artemis.jettaintelligence.com"
CONFIG_DIR = Path.home() / ".artemis"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load_config():
    """Load configuration from ~/.artemis/config.yaml."""
    if not CONFIG_FILE.exists():
        return {}

    if not YAML_AVAILABLE:
        # Fallback: simple key: value parsing
        config = {}
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and ":" in line:
                    key, value = line.split(":", 1)
                    config[key.strip()] = value.strip()
        return config

    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict):
    """Save configuration to ~/.artemis/config.yaml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if YAML_AVAILABLE:
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
    else:
        with open(CONFIG_FILE, "w") as f:
            for key, value in config.items():
                f.write(f"{key}: {value}\n")

    # Secure permissions (owner read/write only)
    CONFIG_FILE.chmod(0o600)


def get_master_key():
    """Get master API key from environment or config file."""
    # 1. Check environment variable
    key = os.environ.get("MASTER_API_KEY")
    if key:
        return key

    # 2. Check config file
    config = load_config()
    key = config.get("master_api_key")
    if key:
        return key

    print("Error: MASTER_API_KEY not found", file=sys.stderr)
    print("Set it with:", file=sys.stderr)
    print("  export MASTER_API_KEY=your_master_key", file=sys.stderr)
    print("  or: artemis-cli.py config set master_api_key your_master_key", file=sys.stderr)
    sys.exit(1)


def get_api_key():
    """Get API key from environment or config file."""
    # 1. Check environment variable
    key = os.environ.get("ARTEMIS_API_KEY")
    if key:
        return key

    # 2. Check config file
    config = load_config()
    key = config.get("api_key")
    if key:
        return key

    print("Error: ARTEMIS_API_KEY not found", file=sys.stderr)
    print("Set it with:", file=sys.stderr)
    print("  export ARTEMIS_API_KEY=art_your_key_here", file=sys.stderr)
    print("  or: artemis-cli.py config set api_key art_your_key_here", file=sys.stderr)
    sys.exit(1)


def get_artemis_url(args_url: str = None):
    """Get Artemis URL from args, environment, or config file."""
    # 1. Command line argument
    if args_url and args_url != DEFAULT_ARTEMIS_URL:
        return args_url

    # 2. Environment variable
    url = os.environ.get("ARTEMIS_URL")
    if url:
        return url

    # 3. Config file
    config = load_config()
    url = config.get("url")
    if url:
        return url

    return DEFAULT_ARTEMIS_URL


def api_request(method: str, endpoint: str, artemis_url: str, data: dict = None,
                use_master_key: bool = False, timeout: int = 30):
    """Make an API request to Artemis."""
    url = f"{artemis_url.rstrip('/')}{endpoint}"

    if use_master_key:
        api_key = get_master_key()
    else:
        api_key = get_api_key()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = json.dumps(data).encode() if data else None

    req = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except HTTPError as e:
        error_body = e.read().decode()
        try:
            error_json = json.loads(error_body)
            detail = error_json.get("detail", error_json.get("error", {}).get("message", error_body))
        except json.JSONDecodeError:
            detail = error_body
        print(f"Error {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        sys.exit(1)


# =============================================================================
# Admin Commands (MASTER_API_KEY)
# =============================================================================

def cmd_admin_create_account(args):
    """Create a service account."""
    data = {"name": args.name}
    if args.description:
        data["description"] = args.description

    result = api_request("POST", "/api/v1/admin/service-accounts", args.artemis_url,
                        data, use_master_key=True)

    print(f"✓ Created service account: {result['name']}")
    print(f"  Service Account ID: {result['service_account_id']}")
    print(f"  Group ID: {result['group_id']}")
    print(f"  API Key: {result['api_key']}")
    print(f"  Key Prefix: {result['key_prefix']}")
    print()
    print("Save this API key securely - it won't be shown again!")

    if args.json:
        print(json.dumps(result, indent=2))


def cmd_admin_list_accounts(args):
    """List service accounts."""
    result = api_request("GET", "/api/v1/admin/service-accounts", args.artemis_url,
                        use_master_key=True)

    accounts = result.get("service_accounts", [])
    if not accounts:
        print("No service accounts found.")
        return

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"{'Name':<25} {'ID':<40} {'Created':<20}")
    print("-" * 85)
    for acc in accounts:
        created = acc.get("created_at", "")[:19] if acc.get("created_at") else "N/A"
        print(f"{acc['name']:<25} {acc['id']:<40} {created:<20}")


def cmd_admin_issue_key(args):
    """Issue a new API key for a service account."""
    data = {
        "service_account_name": args.account_name,
        "key_name": args.name,
    }

    result = api_request("POST", "/api/v1/admin/keys", args.artemis_url,
                        data, use_master_key=True)

    print(f"✓ Issued key for: {result['service_account']}")
    print(f"  Key ID: {result['id']}")
    print(f"  Name: {result['name']}")
    print(f"  API Key: {result['api_key']}")
    print(f"  Prefix: {result['key_prefix']}")
    print()
    print("Save this API key securely - it won't be shown again!")


def cmd_admin_list_keys(args):
    """List API keys for a service account."""
    result = api_request("GET", f"/api/v1/admin/keys/{args.account_name}", args.artemis_url,
                        use_master_key=True)

    keys = result.get("keys", [])
    if not keys:
        print(f"No keys found for {result.get('service_account', args.account_name)}.")
        return

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"Keys for service account: {result.get('service_account', args.account_name)}")
    print(f"{'Name':<25} {'Prefix':<15} {'Status':<10} {'Last Used':<20}")
    print("-" * 70)
    for key in keys:
        status = "Revoked" if key.get("revoked_at") else "Active"
        last_used = key.get("last_used_at", "Never")[:19] if key.get("last_used_at") else "Never"
        print(f"{key['name']:<25} {key['key_prefix']:<15} {status:<10} {last_used:<20}")


def cmd_admin_add_provider(args):
    """Add a provider API key."""
    data = {
        "provider_id": args.provider_id,
        "api_key": args.key,
        "name": args.name,
    }
    if args.account:
        data["service_account_name"] = args.account

    result = api_request("POST", "/api/v1/admin/provider-keys", args.artemis_url,
                        data, use_master_key=True)

    print(f"✓ Added provider key for: {result['provider_id']}")
    print(f"  Key ID: {result['key_id']}")
    print(f"  Key Suffix: ****{result['key_suffix']}")
    print(f"  Account ID: {result['account_id']}")
    print(f"  Group ID: {result['group_id']}")


def cmd_admin_list_providers(args):
    """List all provider keys."""
    result = api_request("GET", "/api/v1/admin/provider-keys", args.artemis_url,
                        use_master_key=True)

    keys = result.get("provider_keys", [])
    if not keys:
        print("No provider keys found.")
        return

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"{'Provider':<15} {'Name':<20} {'Suffix':<10} {'Group':<15} {'Active':<8} {'Default':<8}")
    print("-" * 80)
    for key in keys:
        active = "Yes" if key.get("is_active") else "No"
        default = "Yes" if key.get("is_default") else "No"
        print(f"{key['provider_id']:<15} {key['name']:<20} ****{key['key_suffix']:<6} {key['group_name']:<15} {active:<8} {default:<8}")


# =============================================================================
# User Commands (ARTEMIS_API_KEY)
# =============================================================================

def cmd_keys_list(args):
    """List API keys for current user."""
    result = api_request("GET", "/api/v1/keys", args.artemis_url)

    keys = result.get("keys", [])
    if not keys:
        print("No API keys found.")
        return

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"{'Name':<30} {'Prefix':<15} {'Status':<10} {'Last Used':<20}")
    print("-" * 75)
    for key in keys:
        status = "Revoked" if key.get("revoked_at") else "Active"
        if key.get("is_system"):
            status = "System"
        last_used = key.get("last_used_at", "Never")[:19] if key.get("last_used_at") else "Never"
        print(f"{key['name']:<30} {key['key_prefix']:<15} {status:<10} {last_used:<20}")


def cmd_keys_create(args):
    """Create a new API key."""
    data = {"name": args.name}
    result = api_request("POST", "/api/v1/keys", args.artemis_url, data)

    print(f"✓ Created key: {result['name']}")
    print(f"  ID: {result['id']}")
    print(f"  Key: {result['key']}")
    print(f"  Prefix: {result['key_prefix']}")
    print()
    print("Save this key securely - it won't be shown again!")


def cmd_keys_revoke(args):
    """Revoke an API key."""
    result = api_request("DELETE", f"/api/v1/keys/{args.key_id}", args.artemis_url)
    print(f"✓ Key revoked: {result.get('id', args.key_id)}")


# =============================================================================
# Embeddings Commands
# =============================================================================

def cmd_embeddings_health(args):
    """Check embeddings endpoint health."""
    # Health endpoint doesn't require auth
    url = f"{args.artemis_url.rstrip('/')}/v1/embeddings/health"
    req = Request(url)

    try:
        with urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())

        status = result.get("status", "unknown")
        ollama = result.get("ollama", "unknown")

        if status == "healthy":
            print(f"✓ Embeddings: {status}")
            print(f"  Ollama: {ollama}")
            if result.get("embedding_models"):
                print(f"  Local models: {', '.join(result['embedding_models'])}")
        else:
            print(f"⚠ Embeddings: {status}")
            print(f"  Ollama: {ollama}")
            print(f"  Message: {result.get('message', 'N/A')}")
            print("  (Will fallback to cloud providers)")

    except HTTPError as e:
        print(f"Error {e.code}: Could not check embeddings health", file=sys.stderr)
        sys.exit(1)


def cmd_embeddings_test(args):
    """Test embedding generation."""
    data = {
        "input": args.text,
        "model": "text-embedding-3-small",
    }

    result = api_request("POST", "/v1/embeddings", args.artemis_url, data, timeout=60)

    embeddings = result.get("data", [])
    if not embeddings:
        print("Error: No embeddings returned", file=sys.stderr)
        sys.exit(1)

    emb = embeddings[0].get("embedding", [])
    artemis_meta = result.get("_artemis", {})

    print(f"✓ Embedding generated")
    print(f"  Model: {result.get('model', 'unknown')}")
    print(f"  Dimensions: {len(emb)}")
    print(f"  Provider: {artemis_meta.get('provider', 'unknown')}")
    print(f"  Latency: {artemis_meta.get('latency_ms', 'N/A')}ms")
    print(f"  Tokens: {result.get('usage', {}).get('total_tokens', 'N/A')}")

    if args.verbose:
        print(f"\n  First 5 values: {emb[:5]}")
        print(f"  Last 5 values: {emb[-5:]}")

    if args.json:
        print(json.dumps(result, indent=2))


def cmd_embeddings_providers(args):
    """List available embedding providers."""
    result = api_request("GET", "/v1/embeddings/providers", args.artemis_url)

    providers = result.get("providers", [])
    fallback = result.get("fallback_order", [])

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("Available Embedding Providers:")
    print(f"{'Provider':<15} {'Model':<35} {'Dims':<8} {'Has Key':<10}")
    print("-" * 70)
    for p in providers:
        has_key = "Yes" if p.get("has_key") else "No"
        dims = str(p.get("dimensions", "?"))
        print(f"{p['id']:<15} {p['model']:<35} {dims:<8} {has_key:<10}")

    print(f"\nFallback order: {' → '.join(fallback)}")


# =============================================================================
# Config Commands
# =============================================================================

def cmd_config_init(args):
    """Initialize config directory and file."""
    if CONFIG_FILE.exists():
        print(f"Config file already exists: {CONFIG_FILE}")
        config = load_config()
        if config:
            print("Current settings:")
            for key, value in config.items():
                # Mask sensitive values
                if "key" in key.lower() and value:
                    masked = value[:12] + "..." if len(value) > 12 else "***"
                    print(f"  {key}: {masked}")
                else:
                    print(f"  {key}: {value}")
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    save_config({
        "# Artemis CLI Configuration": "",
        "url": DEFAULT_ARTEMIS_URL,
        "# api_key": "art_your_key_here",
        "# master_api_key": "artemis_master_xxx",
    })
    print(f"✓ Created config directory: {CONFIG_DIR}")
    print(f"✓ Created config file: {CONFIG_FILE}")
    print(f"\nEdit the file to add your API keys, or use:")
    print(f"  artemis-cli.py config set api_key art_xxx")
    print(f"  artemis-cli.py config set master_api_key artemis_master_xxx")


def cmd_config_show(args):
    """Show current configuration."""
    config = load_config()

    if not config:
        print(f"No config file found at {CONFIG_FILE}")
        print("Run 'artemis-cli.py config init' to create one")
        return

    if args.json:
        # Mask keys in JSON output
        masked = {}
        for key, value in config.items():
            if "key" in key.lower() and value and not key.startswith("#"):
                masked[key] = value[:12] + "..." if len(value) > 12 else "***"
            else:
                masked[key] = value
        print(json.dumps(masked, indent=2))
        return

    print(f"Config file: {CONFIG_FILE}")
    print("-" * 50)
    for key, value in config.items():
        if key.startswith("#"):
            continue
        if "key" in key.lower() and value:
            masked = value[:12] + "..." if len(value) > 12 else "***"
            print(f"  {key}: {masked}")
        else:
            print(f"  {key}: {value}")

    # Show effective values (including env vars)
    print("\nEffective values (env vars override config):")
    print(f"  ARTEMIS_URL: {get_artemis_url()}")
    if os.environ.get("ARTEMIS_API_KEY"):
        print(f"  ARTEMIS_API_KEY: (from environment)")
    elif config.get("api_key"):
        print(f"  ARTEMIS_API_KEY: (from config)")
    else:
        print(f"  ARTEMIS_API_KEY: (not set)")

    if os.environ.get("MASTER_API_KEY"):
        print(f"  MASTER_API_KEY: (from environment)")
    elif config.get("master_api_key"):
        print(f"  MASTER_API_KEY: (from config)")
    else:
        print(f"  MASTER_API_KEY: (not set)")


def cmd_config_set(args):
    """Set a configuration value."""
    config = load_config()
    config[args.key] = args.value
    save_config(config)

    # Mask the value for display
    if "key" in args.key.lower():
        display_value = args.value[:12] + "..." if len(args.value) > 12 else "***"
    else:
        display_value = args.value

    print(f"✓ Set {args.key} = {display_value}")
    print(f"  Saved to {CONFIG_FILE}")


def cmd_config_get(args):
    """Get a configuration value."""
    config = load_config()
    value = config.get(args.key)

    if value is None:
        print(f"Key '{args.key}' not found in config")
        sys.exit(1)

    if args.raw:
        print(value)
    else:
        if "key" in args.key.lower():
            display_value = value[:12] + "..." if len(value) > 12 else "***"
        else:
            display_value = value
        print(f"{args.key}: {display_value}")


def cmd_config_path(args):
    """Show config file path."""
    print(CONFIG_FILE)


# =============================================================================
# Health Command
# =============================================================================

def cmd_health(args):
    """Check Artemis service health."""
    url = f"{args.artemis_url.rstrip('/')}/health"
    req = Request(url)

    try:
        with urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())

        status = result.get("status", "unknown")
        service = result.get("service", "artemis")
        version = result.get("version", "unknown")

        if status == "healthy":
            print(f"✓ {service} v{version}: {status}")
        else:
            print(f"⚠ {service} v{version}: {status}")

        if args.verbose:
            print(json.dumps(result, indent=2))

    except HTTPError as e:
        print(f"Error {e.code}: Could not check health", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        sys.exit(1)


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Artemis CLI - Programmatic management for Artemis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--artemis-url",
        default=os.environ.get("ARTEMIS_URL", DEFAULT_ARTEMIS_URL),
        help=f"Artemis server URL (default: {DEFAULT_ARTEMIS_URL})"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ==========================================================================
    # Admin commands
    # ==========================================================================
    admin_parser = subparsers.add_parser("admin", help="Admin commands (requires MASTER_API_KEY)")
    admin_subparsers = admin_parser.add_subparsers(dest="admin_command", required=True)

    # admin create-account
    create_acc = admin_subparsers.add_parser("create-account", help="Create a service account")
    create_acc.add_argument("name", help="Service account name (e.g., 'taskr')")
    create_acc.add_argument("--description", "-d", help="Description")
    create_acc.set_defaults(func=cmd_admin_create_account)

    # admin list-accounts
    list_acc = admin_subparsers.add_parser("list-accounts", help="List service accounts")
    list_acc.set_defaults(func=cmd_admin_list_accounts)

    # admin issue-key
    issue_key = admin_subparsers.add_parser("issue-key", help="Issue API key for service account")
    issue_key.add_argument("account_name", help="Service account name")
    issue_key.add_argument("--name", "-n", default="Default", help="Key name")
    issue_key.set_defaults(func=cmd_admin_issue_key)

    # admin list-keys
    list_keys = admin_subparsers.add_parser("list-keys", help="List keys for service account")
    list_keys.add_argument("account_name", help="Service account name")
    list_keys.set_defaults(func=cmd_admin_list_keys)

    # admin add-provider
    add_prov = admin_subparsers.add_parser("add-provider", help="Add provider API key")
    add_prov.add_argument("provider_id", help="Provider ID (e.g., 'openrouter', 'openai')")
    add_prov.add_argument("--key", "-k", required=True, help="Provider API key")
    add_prov.add_argument("--name", "-n", default="Default", help="Key name")
    add_prov.add_argument("--account", "-a", help="Service account to associate with")
    add_prov.set_defaults(func=cmd_admin_add_provider)

    # admin list-providers
    list_prov = admin_subparsers.add_parser("list-providers", help="List provider keys")
    list_prov.set_defaults(func=cmd_admin_list_providers)

    # ==========================================================================
    # Keys commands
    # ==========================================================================
    keys_parser = subparsers.add_parser("keys", help="API key management")
    keys_subparsers = keys_parser.add_subparsers(dest="keys_command", required=True)

    # keys list
    keys_list = keys_subparsers.add_parser("list", help="List your API keys")
    keys_list.set_defaults(func=cmd_keys_list)

    # keys create
    keys_create = keys_subparsers.add_parser("create", help="Create a new API key")
    keys_create.add_argument("--name", "-n", default="Default", help="Key name")
    keys_create.set_defaults(func=cmd_keys_create)

    # keys revoke
    keys_revoke = keys_subparsers.add_parser("revoke", help="Revoke an API key")
    keys_revoke.add_argument("key_id", help="Key ID to revoke")
    keys_revoke.set_defaults(func=cmd_keys_revoke)

    # ==========================================================================
    # Embeddings commands
    # ==========================================================================
    emb_parser = subparsers.add_parser("embeddings", help="Embeddings operations")
    emb_subparsers = emb_parser.add_subparsers(dest="emb_command", required=True)

    # embeddings health
    emb_health = emb_subparsers.add_parser("health", help="Check embeddings health")
    emb_health.set_defaults(func=cmd_embeddings_health)

    # embeddings test
    emb_test = emb_subparsers.add_parser("test", help="Test embedding generation")
    emb_test.add_argument("text", help="Text to embed")
    emb_test.add_argument("--verbose", "-v", action="store_true", help="Show embedding values")
    emb_test.set_defaults(func=cmd_embeddings_test)

    # embeddings providers
    emb_prov = emb_subparsers.add_parser("providers", help="List embedding providers")
    emb_prov.set_defaults(func=cmd_embeddings_providers)

    # ==========================================================================
    # Config commands
    # ==========================================================================
    config_parser = subparsers.add_parser("config", help="Manage local configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)

    # config init
    config_init = config_subparsers.add_parser("init", help="Initialize config file")
    config_init.set_defaults(func=cmd_config_init)

    # config show
    config_show = config_subparsers.add_parser("show", help="Show current configuration")
    config_show.set_defaults(func=cmd_config_show)

    # config set
    config_set = config_subparsers.add_parser("set", help="Set a configuration value")
    config_set.add_argument("key", help="Config key (api_key, master_api_key, url)")
    config_set.add_argument("value", help="Config value")
    config_set.set_defaults(func=cmd_config_set)

    # config get
    config_get = config_subparsers.add_parser("get", help="Get a configuration value")
    config_get.add_argument("key", help="Config key to get")
    config_get.add_argument("--raw", action="store_true", help="Output raw value (for scripts)")
    config_get.set_defaults(func=cmd_config_get)

    # config path
    config_path = config_subparsers.add_parser("path", help="Show config file path")
    config_path.set_defaults(func=cmd_config_path)

    # ==========================================================================
    # Health command
    # ==========================================================================
    health_parser = subparsers.add_parser("health", help="Check Artemis health")
    health_parser.add_argument("--verbose", "-v", action="store_true", help="Show full response")
    health_parser.set_defaults(func=cmd_health)

    # ==========================================================================
    # Parse and execute
    # ==========================================================================
    args = parser.parse_args()

    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
