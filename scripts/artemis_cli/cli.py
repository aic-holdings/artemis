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

import typer
from rich.console import Console
from rich.table import Table

from artemis_cli.api import (
    api_request as _api_request,
    load_config,
    save_config,
    get_url,
    get_api_key,
    get_master_key,
    APIError,
    ConfigError,
    ConnectionError,
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_URL,
)

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
proxy_app = typer.Typer(help="LLM proxy operations")
models_app = typer.Typer(help="Model management")
whisper_app = typer.Typer(help="Audio transcription (Whisper)")

app.add_typer(admin_app, name="admin")
app.add_typer(keys_app, name="keys")
app.add_typer(embeddings_app, name="embeddings")
app.add_typer(config_app, name="config")
app.add_typer(proxy_app, name="proxy")
app.add_typer(models_app, name="models")
app.add_typer(whisper_app, name="whisper")

# Rich console for colored output
console = Console()
err_console = Console(stderr=True)


def api_request(method: str, endpoint: str, data: dict = None,
                use_master: bool = False, timeout: int = 30) -> dict:
    """Make API request with CLI error handling."""
    try:
        return _api_request(method, endpoint, data, use_master, timeout)
    except APIError as e:
        err_console.print(f"[red]Error {e.status_code}:[/red] {e.detail}")
        raise typer.Exit(1)
    except ConfigError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except ConnectionError as e:
        err_console.print(f"[red]{e}[/red]")
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
# Proxy Commands
# =============================================================================

@proxy_app.command("test")
def proxy_test(
    prompt: str = typer.Argument("Say hello in exactly 5 words.", help="Prompt to send"),
    model: str = typer.Option("openai/gpt-4o-mini", "--model", "-m", help="Model to use"),
    provider: str = typer.Option("openrouter", "--provider", "-p", help="Provider (openrouter, openai, anthropic)"),
    web: bool = typer.Option(False, "--web", "-w", help="Enable web search (OpenRouter only)"),
    web_results: int = typer.Option(5, "--web-results", help="Max web search results (1-10)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full response"),
):
    """Test LLM proxy with a simple prompt.

    Example: artemis proxy test "What is 2+2?"
    Example: artemis proxy test "Hello" --model anthropic/claude-3-haiku
    Example: artemis proxy test "Latest AI news" --web
    Example: artemis proxy test "Current weather in NYC" --web --web-results 3
    """
    # Handle web search - can use :online suffix or plugins array
    effective_model = model
    if web and provider == "openrouter":
        # Use plugins array for more control
        pass  # We'll add plugins below
    elif web:
        console.print("[yellow]Warning: --web only works with OpenRouter provider[/yellow]")

    data = {
        "model": effective_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500 if web else 100,  # More tokens for web results
    }

    # Add web search plugin if enabled
    if web and provider == "openrouter":
        data["plugins"] = [{"id": "web", "max_results": web_results}]

    search_indicator = " [cyan](web search)[/cyan]" if web else ""
    console.print(f"[dim]Sending to {provider}/{model}...{search_indicator}[/dim]")

    try:
        result = api_request("POST", f"/v1/{provider}/chat/completions", data, timeout=60)
    except Exception:
        raise

    choices = result.get("choices", [])
    if not choices:
        err_console.print("[red]Error:[/red] No response from model")
        raise typer.Exit(1)

    message = choices[0].get("message", {})
    content = message.get("content", "")
    usage = result.get("usage", {})
    meta = result.get("_artemis", {})

    console.print(f"[green]✓[/green] Response received")
    console.print(f"  Model: [cyan]{result.get('model')}[/cyan]")
    console.print(f"  Provider: [cyan]{meta.get('provider', provider)}[/cyan]")
    console.print(f"  Latency: [cyan]{meta.get('latency_ms', 'N/A')}ms[/cyan]")
    console.print(f"  Tokens: [dim]in={usage.get('prompt_tokens', 'N/A')} out={usage.get('completion_tokens', 'N/A')}[/dim]")

    # Show web search info if present (OpenRouter web search)
    annotations = message.get("annotations", [])
    citations = [a for a in annotations if a.get("type") == "url_citation"]
    if citations:
        console.print(f"  Web Sources: [cyan]{len(citations)}[/cyan]")

    console.print(f"\n[bold]Response:[/bold] {content}")

    # Show citations if any (OpenRouter nests under url_citation)
    if citations:
        console.print(f"\n[bold]Sources:[/bold]")
        seen_urls = set()
        for i, cite in enumerate(citations[:5], 1):  # Limit to 5
            # Handle nested url_citation structure
            cite_data = cite.get("url_citation", cite)
            url = cite_data.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title = cite_data.get("title", url)
            console.print(f"  {i}. [dim]{title}[/dim]")
            console.print(f"     [blue]{url}[/blue]")

    if verbose:
        console.print(f"\n[dim]Full response:[/dim]")
        console.print(json.dumps(result, indent=2))


# =============================================================================
# Models Commands
# =============================================================================

@models_app.command("list")
def models_list(
    provider: str = typer.Option(None, "--provider", "-p", help="Filter by provider"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List available models.

    Example: artemis models list
    Example: artemis models list --provider openai
    """
    if provider:
        result = api_request("GET", f"/api/v1/providers/{provider}/models")
        models = result.get("models", [])
    else:
        result = api_request("GET", "/v1/models")
        models = result.get("models", result.get("data", []))

    if as_json:
        console.print(json.dumps(result, indent=2))
        return

    if not models:
        console.print("No models found.")
        return

    table = Table()
    table.add_column("Model", style="cyan")
    table.add_column("Provider")
    table.add_column("Context", justify="right")

    for m in models[:50]:  # Limit display
        model_id = m.get("id", m.get("model_id", ""))
        prov = m.get("provider", m.get("provider_name", model_id.split("/")[0] if "/" in model_id else ""))
        context = m.get("context_window", m.get("context_length", ""))
        table.add_row(model_id, prov, str(context) if context else "")

    console.print(table)
    if len(models) > 50:
        console.print(f"\n[dim]Showing 50 of {len(models)} models. Use --json for full list.[/dim]")


@models_app.command("pricing")
def models_pricing(
    provider: str = typer.Argument(..., help="Provider name (openai, anthropic, etc.)"),
    model: str = typer.Argument(..., help="Model name"),
):
    """Show pricing for a specific model.

    Example: artemis models pricing openai gpt-4o
    Example: artemis models pricing anthropic claude-3-opus
    """
    result = api_request("GET", f"/api/model-pricing/{provider}/{model}")

    if not result:
        console.print(f"[yellow]No pricing found for {provider}/{model}[/yellow]")
        return

    console.print(f"[bold]Pricing: {provider}/{model}[/bold]\n")
    console.print(f"  Input:  [cyan]${result.get('input_cost', 0):.4f}[/cyan] / 1K tokens")
    console.print(f"  Output: [cyan]${result.get('output_cost', 0):.4f}[/cyan] / 1K tokens")

    if result.get("context_length"):
        console.print(f"  Context: [dim]{result.get('context_length')} tokens[/dim]")


# =============================================================================
# Whisper Commands
# =============================================================================

@whisper_app.command("test")
def whisper_test(
    file_path: str = typer.Argument(..., help="Path to audio file (mp3, wav, m4a, etc.)"),
    model: str = typer.Option("whisper-1", "--model", "-m", help="Whisper model"),
    language: str = typer.Option(None, "--language", "-l", help="Language code (e.g., en, es)"),
):
    """Test audio transcription with Whisper.

    Example: artemis whisper test audio.mp3
    Example: artemis whisper test meeting.m4a --language en
    """
    import base64
    from pathlib import Path as FilePath

    audio_path = FilePath(file_path)
    if not audio_path.exists():
        err_console.print(f"[red]Error:[/red] File not found: {file_path}")
        raise typer.Exit(1)

    # Read and encode file
    with open(audio_path, "rb") as f:
        audio_data = f.read()

    file_size_mb = len(audio_data) / (1024 * 1024)
    console.print(f"[dim]Uploading {audio_path.name} ({file_size_mb:.1f} MB)...[/dim]")

    # Build multipart form data manually using urllib
    import mimetypes
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError

    boundary = "----ArtemisWhisperBoundary"
    content_type = mimetypes.guess_type(file_path)[0] or "audio/mpeg"

    body = []
    # File field
    body.append(f"--{boundary}".encode())
    body.append(f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"'.encode())
    body.append(f"Content-Type: {content_type}".encode())
    body.append(b"")
    body.append(audio_data)
    # Model field
    body.append(f"--{boundary}".encode())
    body.append(b'Content-Disposition: form-data; name="model"')
    body.append(b"")
    body.append(model.encode())
    # Language field (optional)
    if language:
        body.append(f"--{boundary}".encode())
        body.append(b'Content-Disposition: form-data; name="language"')
        body.append(b"")
        body.append(language.encode())
    body.append(f"--{boundary}--".encode())

    body_bytes = b"\r\n".join(body)

    url = f"{get_url().rstrip('/')}/v1/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    req = Request(url, data=body_bytes, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=300) as resp:  # 5 min timeout for large files
            result = json.loads(resp.read().decode())
    except HTTPError as e:
        try:
            error = json.loads(e.read().decode())
            detail = error.get("detail", str(error))
        except:
            detail = f"HTTP {e.code}"
        err_console.print(f"[red]Error {e.code}:[/red] {detail}")
        raise typer.Exit(1)

    text = result.get("text", "")
    meta = result.get("_artemis", {})

    console.print(f"[green]✓[/green] Transcription complete")
    console.print(f"  Model: [cyan]{model}[/cyan]")
    console.print(f"  Provider: [cyan]{meta.get('provider', 'openai')}[/cyan]")
    console.print(f"  Latency: [cyan]{meta.get('latency_ms', 'N/A')}ms[/cyan]")
    console.print(f"  Duration: [dim]{meta.get('audio_duration', 'N/A')}s[/dim]")
    console.print(f"\n[bold]Transcript:[/bold]\n{text}")


@whisper_app.command("providers")
def whisper_providers():
    """List audio transcription providers.

    Example: artemis whisper providers
    """
    result = api_request("GET", "/v1/audio/providers")
    providers = result.get("providers", [])

    if not providers:
        console.print("No audio providers configured.")
        return

    table = Table()
    table.add_column("Provider", style="cyan")
    table.add_column("Model")
    table.add_column("Has Key")

    for p in providers:
        has_key = "[green]Yes[/green]" if p.get("has_key") else "[red]No[/red]"
        table.add_row(p.get("id"), p.get("model", "whisper-1"), has_key)

    console.print(table)


# =============================================================================
# Usage/Status Commands
# =============================================================================

@app.command("usage")
def usage_cmd(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show usage statistics and budget.

    Example: artemis usage
    """
    result = api_request("GET", "/v1/budget")

    if as_json:
        console.print(json.dumps(result, indent=2))
        return

    console.print("[bold]Usage Statistics[/bold]\n")

    # Budget info
    budget = result.get("budget", {})
    if budget:
        limit = budget.get("limit")
        used = budget.get("used", 0)
        remaining = budget.get("remaining")
        console.print(f"  Budget Limit: [cyan]${limit:.2f}[/cyan]" if limit else "  Budget: [dim]Unlimited[/dim]")
        console.print(f"  Used: [cyan]${used:.4f}[/cyan]")
        if remaining is not None:
            console.print(f"  Remaining: [cyan]${remaining:.2f}[/cyan]")

    # Token usage
    tokens = result.get("tokens", {})
    if tokens:
        console.print(f"\n  Input Tokens: [dim]{tokens.get('input', 0):,}[/dim]")
        console.print(f"  Output Tokens: [dim]{tokens.get('output', 0):,}[/dim]")
        console.print(f"  Total Tokens: [dim]{tokens.get('total', 0):,}[/dim]")

    # Request counts
    requests = result.get("requests", {})
    if requests:
        console.print(f"\n  Total Requests: [dim]{requests.get('total', 0):,}[/dim]")
        console.print(f"  This Period: [dim]{requests.get('period', 0):,}[/dim]")


@app.command("breakdown")
def breakdown_cmd(
    days: int = typer.Option(30, "--days", "-d", help="Number of days to look back"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max items per category"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show detailed usage breakdown by model, provider, and day.

    Example: artemis breakdown --days 7
    """
    result = api_request("GET", f"/v1/usage/breakdown?days={days}&limit={limit}")

    if as_json:
        console.print(json.dumps(result, indent=2))
        return

    totals = result.get("totals", {})
    period = result.get("period", {})

    console.print(f"[bold]Usage Breakdown[/bold] (last {period.get('days', days)} days)\n")
    console.print(f"  Total Requests: [cyan]{totals.get('requests', 0):,}[/cyan]")
    console.print(f"  Total Cost: [cyan]${totals.get('cost_usd', 0):.4f}[/cyan]")
    console.print(f"  Total Tokens: [cyan]{totals.get('tokens', 0):,}[/cyan]")

    # By Model
    by_model = result.get("by_model", {})
    if by_model:
        console.print("\n[bold]By Model:[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Model", style="cyan")
        table.add_column("Requests", justify="right")
        table.add_column("Cost", justify="right", style="green")
        table.add_column("Tokens", justify="right")
        for model, data in by_model.items():
            table.add_row(
                model[:40],
                f"{data['requests']:,}",
                f"${data['cost_usd']:.4f}",
                f"{data['tokens']:,}",
            )
        console.print(table)

    # By Provider
    by_provider = result.get("by_provider", {})
    if by_provider:
        console.print("\n[bold]By Provider:[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Provider", style="cyan")
        table.add_column("Requests", justify="right")
        table.add_column("Cost", justify="right", style="green")
        table.add_column("Tokens", justify="right")
        for provider, data in by_provider.items():
            table.add_row(
                provider,
                f"{data['requests']:,}",
                f"${data['cost_usd']:.4f}",
                f"{data['tokens']:,}",
            )
        console.print(table)

    # By Day (last 7)
    by_day = result.get("by_day", {})
    if by_day:
        console.print("\n[bold]By Day (recent):[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Date", style="cyan")
        table.add_column("Requests", justify="right")
        table.add_column("Cost", justify="right", style="green")
        table.add_column("Tokens", justify="right")
        for day, data in list(by_day.items())[:7]:
            table.add_row(
                day,
                f"{data['requests']:,}",
                f"${data['cost_usd']:.4f}",
                f"{data['tokens']:,}",
            )
        console.print(table)

    # Recent requests
    recent = result.get("recent_requests", [])
    if recent:
        console.print(f"\n[bold]Recent Requests[/bold] (last {len(recent)}):")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Time", style="dim")
        table.add_column("Model")
        table.add_column("In", justify="right")
        table.add_column("Out", justify="right")
        table.add_column("Cost", justify="right", style="green")
        table.add_column("App")
        for req in recent[:10]:
            ts = req.get("timestamp", "")[:19].replace("T", " ")
            table.add_row(
                ts,
                req.get("model", "")[:30],
                f"{req.get('input_tokens', 0):,}",
                f"{req.get('output_tokens', 0):,}",
                f"${req.get('cost_usd', 0):.4f}",
                req.get("app_id", "-")[:15] if req.get("app_id") else "-",
            )
        console.print(table)


@app.command("status")
def status_cmd(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full details"),
):
    """Show detailed system status.

    Example: artemis status
    """
    # Get basic health
    url = f"{get_url().rstrip('/')}/health"
    req = Request(url)

    try:
        with urlopen(req, timeout=10) as resp:
            health = json.loads(resp.read().decode())
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    status = health.get("status", "unknown")
    version = health.get("version", "?")
    service = health.get("service", "artemis")

    if status == "healthy":
        console.print(f"[green]✓[/green] {service} v{version}: [green]{status}[/green]")
    else:
        console.print(f"[yellow]⚠[/yellow] {service} v{version}: [yellow]{status}[/yellow]")

    # Get embeddings health
    try:
        emb_url = f"{get_url().rstrip('/')}/v1/embeddings/health"
        emb_req = Request(emb_url)
        with urlopen(emb_req, timeout=10) as resp:
            emb_health = json.loads(resp.read().decode())
        emb_status = emb_health.get("status", "unknown")
        emb_mode = emb_health.get("mode", "unknown")
        emb_icon = "[green]✓[/green]" if emb_status == "healthy" else "[yellow]⚠[/yellow]"
        console.print(f"  {emb_icon} Embeddings: {emb_status} ({emb_mode})")
    except Exception:
        console.print(f"  [yellow]⚠[/yellow] Embeddings: unknown")

    # Get providers info
    try:
        providers = api_request("GET", "/v1/embeddings/providers")
        provider_list = providers.get("providers", [])
        console.print(f"\n[bold]Embedding Providers:[/bold]")
        for p in provider_list:
            has_key = p.get("has_key", False)
            icon = "[green]✓[/green]" if has_key else "[red]✗[/red]"
            console.print(f"  {icon} {p.get('id')}: {'configured' if has_key else 'no key'}")
    except Exception:
        pass

    # Show auth info
    auth = health.get("auth", {})
    if auth:
        console.print(f"\n[bold]Auth:[/bold]")
        console.print(f"  Provider: {auth.get('provider', 'unknown')}")
        console.print(f"  SSO: {'enabled' if auth.get('sso_enabled') else 'disabled'}")

    if verbose:
        console.print(f"\n[dim]Health response:[/dim]")
        console.print(json.dumps(health, indent=2))


# =============================================================================
# Main
# =============================================================================

def main():
    app()


if __name__ == "__main__":
    main()
