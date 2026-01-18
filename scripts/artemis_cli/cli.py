#!/usr/bin/env python3
"""
Artemis CLI - AI API proxy management.

Commands:
    admin       Admin commands (requires MASTER_API_KEY)
    keys        API key management
    embeddings  Embeddings operations
    config      Manage local configuration
    health      Check Artemis health
"""
import json
import sys
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import typer
from rich.console import Console
from rich.table import Table

# Initialize Typer apps
app = typer.Typer(
    name="artemis",
    help="Artemis CLI - AI API proxy management",
    no_args_is_help=True,
)
admin_app = typer.Typer(help="Admin commands (requires MASTER_API_KEY)")
keys_app = typer.Typer(help="API key management")
embeddings_app = typer.Typer(help="Embeddings operations")
config_app = typer.Typer(help="Manage local configuration (~/.artemis)")

app.add_typer(admin_app, name="admin")
app.add_typer(keys_app, name="keys")
app.add_typer(embeddings_app, name="embeddings")
app.add_typer(config_app, name="config")

# Rich console for colored output
console = Console()
err_console = Console(stderr=True)

# Config
DEFAULT_URL = "https://artemis.jettaintelligence.com"
CONFIG_DIR = Path.home() / ".artemis"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


# =============================================================================
# Config Helpers
# =============================================================================

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
    import os
    return os.environ.get("ARTEMIS_URL") or load_config().get("url") or DEFAULT_URL


def get_api_key() -> str:
    """Get API key from env or config."""
    import os
    key = os.environ.get("ARTEMIS_API_KEY") or load_config().get("api_key")
    if not key:
        err_console.print("[red]Error:[/red] ARTEMIS_API_KEY not found")
        err_console.print("Set with: [cyan]export ARTEMIS_API_KEY=art_xxx[/cyan]")
        err_console.print("Or: [cyan]artemis config set api_key art_xxx[/cyan]")
        raise typer.Exit(1)
    return key


def get_master_key() -> str:
    """Get master API key from env or config."""
    import os
    key = os.environ.get("MASTER_API_KEY") or load_config().get("master_api_key")
    if not key:
        err_console.print("[red]Error:[/red] MASTER_API_KEY not found")
        err_console.print("Set with: [cyan]export MASTER_API_KEY=xxx[/cyan]")
        err_console.print("Or: [cyan]artemis config set master_api_key xxx[/cyan]")
        raise typer.Exit(1)
    return key


def api_request(method: str, endpoint: str, data: dict = None,
                use_master: bool = False, timeout: int = 30) -> dict:
    """Make API request to Artemis."""
    url = f"{get_url().rstrip('/')}{endpoint}"
    key = get_master_key() if use_master else get_api_key()

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
            err_console.print(f"[red]Error {e.code}:[/red] {error.get('detail', str(error))}")
        except:
            err_console.print(f"[red]Error {e.code}[/red]")
        raise typer.Exit(1)
    except URLError as e:
        err_console.print(f"[red]Connection error:[/red] {e.reason}")
        raise typer.Exit(1)


def mask_key(key: str) -> str:
    """Mask a sensitive key for display."""
    if not key:
        return ""
    return key[:12] + "..." if len(key) > 12 else "***"


# =============================================================================
# Config Commands
# =============================================================================

@config_app.command("init")
def config_init():
    """Initialize config directory and file.

    Example: artemis config init
    """
    if CONFIG_FILE.exists():
        console.print(f"Config already exists: [cyan]{CONFIG_FILE}[/cyan]")
        config = load_config()
        if config:
            console.print("\nCurrent settings:")
            for k, v in config.items():
                if "key" in k.lower():
                    v = mask_key(v)
                console.print(f"  {k}: [dim]{v}[/dim]")
        return

    save_config({"url": DEFAULT_URL})
    console.print(f"[green]✓[/green] Created: [cyan]{CONFIG_FILE}[/cyan]")
    console.print("\nAdd your keys:")
    console.print("  [cyan]artemis config set api_key art_xxx[/cyan]")
    console.print("  [cyan]artemis config set master_api_key xxx[/cyan]")


@config_app.command("show")
def config_show(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show current configuration.

    Example: artemis config show
    """
    config = load_config()

    if not config:
        console.print(f"No config at [cyan]{CONFIG_FILE}[/cyan]")
        console.print("Run: [cyan]artemis config init[/cyan]")
        return

    if as_json:
        masked = {k: mask_key(v) if "key" in k.lower() else v for k, v in config.items()}
        console.print(json.dumps(masked, indent=2))
        return

    console.print(f"[bold]Config:[/bold] {CONFIG_FILE}\n")
    for k, v in config.items():
        if k.startswith("#"):
            continue
        if "key" in k.lower():
            v = mask_key(v)
        console.print(f"  {k}: [cyan]{v}[/cyan]")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key (api_key, master_api_key, url)"),
    value: str = typer.Argument(..., help="Config value"),
):
    """Set a configuration value.

    Example: artemis config set api_key art_xxx
    """
    config = load_config()
    config[key] = value
    save_config(config)
    display = mask_key(value) if "key" in key.lower() else value
    console.print(f"[green]✓[/green] Set {key} = [cyan]{display}[/cyan]")


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Config key"),
    raw: bool = typer.Option(False, "--raw", help="Output raw value"),
):
    """Get a configuration value.

    Example: artemis config get api_key --raw
    """
    config = load_config()
    value = config.get(key)
    if value is None:
        err_console.print(f"[red]Key not found:[/red] {key}")
        raise typer.Exit(1)

    if raw:
        print(value)
    else:
        display = mask_key(value) if "key" in key.lower() else value
        console.print(f"{key}: [cyan]{display}[/cyan]")


@config_app.command("path")
def config_path():
    """Show config file path.

    Example: artemis config path
    """
    print(CONFIG_FILE)


# =============================================================================
# Admin Commands
# =============================================================================

@admin_app.command("create-account")
def admin_create_account(
    name: str = typer.Argument(..., help="Service account name (e.g., 'taskr')"),
    description: str = typer.Option(None, "--description", "-d", help="Description"),
):
    """Create a service account.

    Example: artemis admin create-account taskr --description "Taskr service"
    """
    data = {"name": name}
    if description:
        data["description"] = description

    result = api_request("POST", "/api/v1/admin/service-accounts", data, use_master=True)

    sa = result.get("service_account", {})
    group = result.get("group", {})
    key = result.get("api_key", {})

    console.print(f"[green]✓[/green] Created service account: [bold]{name}[/bold]")
    console.print(f"  ID: [dim]{sa.get('id')}[/dim]")
    console.print(f"  Group: [dim]{group.get('id')}[/dim]")
    console.print(f"  API Key: [cyan]{key.get('key')}[/cyan]")
    console.print(f"  Prefix: [dim]{key.get('key_prefix')}[/dim]")
    console.print("\n[yellow]Save this key - it won't be shown again![/yellow]")


@admin_app.command("list-accounts")
def admin_list_accounts(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List service accounts.

    Example: artemis admin list-accounts
    """
    result = api_request("GET", "/api/v1/admin/service-accounts", use_master=True)
    accounts = result.get("service_accounts", [])

    if as_json:
        console.print(json.dumps(result, indent=2))
        return

    if not accounts:
        console.print("No service accounts found.")
        return

    table = Table()
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Created")

    for acc in accounts:
        created = acc.get("created_at", "")[:19].replace("T", " ")
        table.add_row(acc.get("name"), acc.get("id"), created)

    console.print(table)


@admin_app.command("issue-key")
def admin_issue_key(
    account_name: str = typer.Argument(..., help="Service account name"),
    name: str = typer.Option("Default", "--name", "-n", help="Key name"),
):
    """Issue API key for service account.

    Example: artemis admin issue-key taskr --name production
    """
    result = api_request("POST", f"/api/v1/admin/keys/{account_name}",
                        {"name": name}, use_master=True)

    key = result.get("api_key", {})
    console.print(f"[green]✓[/green] Issued key: [bold]{name}[/bold]")
    console.print(f"  ID: [dim]{key.get('id')}[/dim]")
    console.print(f"  Key: [cyan]{key.get('key')}[/cyan]")
    console.print(f"  Prefix: [dim]{key.get('key_prefix')}[/dim]")
    console.print("\n[yellow]Save this key - it won't be shown again![/yellow]")


@admin_app.command("list-keys")
def admin_list_keys(
    account_name: str = typer.Argument(..., help="Service account name"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List keys for service account.

    Example: artemis admin list-keys taskr
    """
    result = api_request("GET", f"/api/v1/admin/keys/{account_name}", use_master=True)
    keys = result.get("api_keys", [])

    if as_json:
        console.print(json.dumps(result, indent=2))
        return

    console.print(f"[bold]Keys for:[/bold] {account_name}\n")

    if not keys:
        console.print("No keys found.")
        return

    table = Table()
    table.add_column("Name", style="cyan")
    table.add_column("Prefix", style="dim")
    table.add_column("Status")
    table.add_column("Last Used")

    for k in keys:
        status = "[red]Revoked[/red]" if k.get("revoked_at") else "[green]Active[/green]"
        last_used = (k.get("last_used_at") or "Never")[:19].replace("T", " ")
        table.add_row(k.get("name"), k.get("key_prefix"), status, last_used)

    console.print(table)


@admin_app.command("add-provider")
def admin_add_provider(
    provider_id: str = typer.Argument(..., help="Provider (openrouter, openai, voyage)"),
    key: str = typer.Option(..., "--key", "-k", help="Provider API key"),
    name: str = typer.Option("Default", "--name", "-n", help="Key name"),
    account: str = typer.Option(None, "--account", "-a", help="Service account name"),
):
    """Add provider API key.

    Example: artemis admin add-provider openrouter --key sk-or-v1-xxx --account taskr
    """
    data = {"provider_id": provider_id, "api_key": key, "name": name}
    if account:
        data["service_account_name"] = account

    result = api_request("POST", "/api/v1/admin/provider-keys", data, use_master=True)

    pk = result.get("provider_key", {})
    console.print(f"[green]✓[/green] Added provider: [bold]{provider_id}[/bold]")
    console.print(f"  ID: [dim]{pk.get('id')}[/dim]")
    console.print(f"  Suffix: [dim]****{key[-4:]}[/dim]")


@admin_app.command("list-providers")
def admin_list_providers(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List provider keys.

    Example: artemis admin list-providers
    """
    result = api_request("GET", "/api/v1/admin/provider-keys", use_master=True)
    providers = result.get("provider_keys", [])

    if as_json:
        console.print(json.dumps(result, indent=2))
        return

    if not providers:
        console.print("No provider keys found.")
        return

    table = Table()
    table.add_column("Provider", style="cyan")
    table.add_column("Name")
    table.add_column("Suffix", style="dim")
    table.add_column("Group")
    table.add_column("Active")
    table.add_column("Default")

    for p in providers:
        active = "[green]Yes[/green]" if p.get("is_active") else "[red]No[/red]"
        default = "[green]Yes[/green]" if p.get("is_default") else "No"
        table.add_row(
            p.get("provider_id"), p.get("name"), p.get("key_suffix"),
            p.get("group_name", "Default"), active, default
        )

    console.print(table)


# =============================================================================
# Embeddings Commands
# =============================================================================

@embeddings_app.command("health")
def embeddings_health():
    """Check embeddings health.

    Example: artemis embeddings health
    """
    url = f"{get_url().rstrip('/')}/v1/embeddings/health"
    req = Request(url)

    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())

        status = result.get("status", "unknown")
        mode = result.get("mode", "unknown")
        ollama = result.get("ollama", "unknown")

        if status == "healthy":
            console.print(f"[green]✓[/green] Embeddings: [green]{status}[/green]")
            console.print(f"  Mode: [cyan]{mode}[/cyan]")
            console.print(f"  Ollama: [dim]{ollama}[/dim]")
        else:
            console.print(f"[yellow]⚠[/yellow] Embeddings: [yellow]{status}[/yellow]")
            console.print(f"  Ollama: [dim]{ollama}[/dim]")
            console.print(f"  [dim]{result.get('message', '')}[/dim]")
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@embeddings_app.command("test")
def embeddings_test(
    text: str = typer.Argument(..., help="Text to embed"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show embedding values"),
):
    """Test embedding generation.

    Example: artemis embeddings test "Hello world"
    """
    data = {"input": text, "model": "text-embedding-3-small"}
    result = api_request("POST", "/v1/embeddings", data, timeout=60)

    embeddings = result.get("data", [])
    if not embeddings:
        err_console.print("[red]Error:[/red] No embeddings returned")
        raise typer.Exit(1)

    emb = embeddings[0].get("embedding", [])
    meta = result.get("_artemis", {})

    console.print("[green]✓[/green] Embedding generated")
    console.print(f"  Model: [cyan]{result.get('model')}[/cyan]")
    console.print(f"  Dimensions: [cyan]{len(emb)}[/cyan]")
    console.print(f"  Provider: [cyan]{meta.get('provider')}[/cyan]")
    console.print(f"  Latency: [cyan]{meta.get('latency_ms')}ms[/cyan]")
    console.print(f"  Tokens: [dim]{result.get('usage', {}).get('total_tokens')}[/dim]")

    if verbose:
        console.print(f"\n  First 5: {emb[:5]}")
        console.print(f"  Last 5: {emb[-5:]}")


@embeddings_app.command("providers")
def embeddings_providers(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List embedding providers.

    Example: artemis embeddings providers
    """
    result = api_request("GET", "/v1/embeddings/providers")
    providers = result.get("providers", [])
    fallback = result.get("fallback_order", [])

    if as_json:
        console.print(json.dumps(result, indent=2))
        return

    console.print("[bold]Embedding Providers[/bold]\n")

    table = Table()
    table.add_column("Provider", style="cyan")
    table.add_column("Model")
    table.add_column("Dims")
    table.add_column("Has Key")

    for p in providers:
        has_key = "[green]Yes[/green]" if p.get("has_key") else "[red]No[/red]"
        table.add_row(p.get("id"), p.get("model"), str(p.get("dimensions")), has_key)

    console.print(table)
    console.print(f"\nFallback: [cyan]{' → '.join(fallback)}[/cyan]")


# =============================================================================
# Health Command
# =============================================================================

@app.command("health")
def health(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full response"),
):
    """Check Artemis service health.

    Example: artemis health
    """
    url = f"{get_url().rstrip('/')}/health"
    req = Request(url)

    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())

        status = result.get("status", "unknown")
        service = result.get("service", "artemis")
        version = result.get("version", "?")

        if status == "healthy":
            console.print(f"[green]✓[/green] {service} v{version}: [green]{status}[/green]")
        else:
            console.print(f"[yellow]⚠[/yellow] {service} v{version}: [yellow]{status}[/yellow]")

        if verbose:
            console.print(json.dumps(result, indent=2))
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("version")
def version():
    """Show CLI version."""
    console.print("artemis-cli [cyan]v2.0.0[/cyan] (Typer)")


# =============================================================================
# Main
# =============================================================================

def main():
    app()


if __name__ == "__main__":
    main()
