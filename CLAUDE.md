# Artemis - Claude Code Instructions

## CRITICAL RULES - DO NOT VIOLATE

1. **NEVER delete or modify production data** without explicit user confirmation
2. **Production uses PostgreSQL** on Railway - not local SQLite
3. The app auto-creates tables on startup via Alembic migrations

## Environments

### Production (Railway)
- **URL**: https://artemis.jettaintelligence.com
- **Database**: PostgreSQL on Railway (shared with jetta-sso)
- **Deployed via**: Railway (project: `amusing-generosity`)
- **SSO**: Rhea SSO at https://login.meetrhea.com

### Repository
- **Origin**: `aic-holdings/artemis` (main development repo)

### Local Development
```bash
# Start dev server on port 8767
source venv/bin/activate && LOCALHOST_MODE=true uvicorn app.main:app --reload --port 8767

# Or use the start script
./start.sh
```

**Note**: Local dev can use SQLite (`artemis.db`) or PostgreSQL - check `.env` for `DATABASE_URL`.

## Project Overview

Artemis is an AI Management Platform - a unified proxy for LLM API calls with usage tracking, cost analytics, and multi-provider support.

### Key Features
- **LLM Proxy**: Unified API for OpenAI, Anthropic, Google, Perplexity, OpenRouter
- **Whisper Transcription**: Audio transcription via `/v1/audio/transcriptions`
- **Usage Tracking**: Per-request logging with cost calculation
- **Multi-tenant**: Organization -> Group -> Keys hierarchy
- **SSO Integration**: Rhea SSO for authentication

### Key Architecture

- **FastAPI** backend with async SQLAlchemy
- **PostgreSQL** database (production) / SQLite (local dev optional)
- **Jinja2** templates with Tailwind CSS
- **Organization -> Group -> Keys** hierarchy

### Important Patterns

1. **User Context**: Always get via `get_current_user(request, db)` which returns a `UserContext` with `user`, `active_org`, `active_group`
2. **SQLAlchemy Async**: Use `selectinload()` for eager loading relationships, convert to `list()` before passing to templates
3. **Dev Mode**: Set `LOCALHOST_MODE=true` for detailed error pages

### File Structure

```
app/
  main.py          # FastAPI app, exception handlers
  auth.py          # API key generation, JWT, encryption
  models.py        # SQLAlchemy models
  database.py      # DB connection
  routers/         # Route handlers
    embeddings.py  # Vector embeddings endpoint
    whisper.py     # Whisper audio transcription
    proxy_routes.py # LLM API proxy (catch-all, must be last)
  services/        # Business logic
    api_key_service.py  # API key CRUD
  templates/       # Jinja2 HTML templates
  static/          # CSS, JS assets
```

### Running Seed Data

```bash
python scripts/seed_data.py
```

This creates test users, organizations, groups, API keys, and usage data.

## API Keys

### Key Format
Artemis API keys use the format: `art_<43-char-base64>`
- Prefix: `art_`
- Random part: 32-byte URL-safe base64 via `secrets.token_urlsafe(32)`
- Example: `art_oTw6IjUMWz0iskHeNVXJHuZ61M5lnGQrPlr8bw1L044`

### Storage (in `api_keys` table)
- `key_hash`: SHA256 hex digest of full key (used for lookups)
- `key_prefix`: First 12 chars for display (`art_` + 8 chars)
- `encrypted_key`: Fernet-encrypted full key (allows reveal via UI)

### Validation Flow
1. API receives key in `Authorization: Bearer <key>` header
2. Strips "Bearer " prefix if present
3. Computes SHA256 hash of key
4. Looks up `key_hash` in `api_keys` table
5. Returns matching APIKey if found and not revoked

### Creating Keys
Keys must be created via Artemis UI or API - the `key_hash` must exist in the database. External secret stores (Knox, Infisical) can store the full key value, but the hash must be in Artemis DB for validation.

### Key Hierarchy
```
Organization
  └── Group
        └── API Keys (belong to group)
              └── Provider Key Overrides (optional per-key routing)
```

## Embeddings Endpoint

### `/v1/embeddings` (POST)
OpenAI-compatible embeddings endpoint with provider fallback.

**Request:**
```json
{
  "input": "text to embed",
  "model": "text-embedding-3-small"
}
```

**Fallback Order:** OpenRouter → OpenAI → Voyage → Ollama (local)

**Response includes `_artemis` metadata:**
```json
{
  "data": [...],
  "_artemis": {
    "provider": "openrouter",
    "dimensions": 1536,
    "latency_ms": 245
  }
}
```

### `/v1/embeddings/health` (GET)
Check Ollama availability (no auth required).

### `/v1/embeddings/providers` (GET)
List available embedding providers and their status (requires auth).
