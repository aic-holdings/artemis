# Artemis - Claude Code Instructions

## CRITICAL RULES - DO NOT VIOLATE

1. **NEVER delete or modify production data** without explicit user confirmation
2. **Production uses PostgreSQL** on Coolify (`artemis-db` service) - not local SQLite
3. The app auto-creates tables on startup via Alembic migrations

## Environments

### Production (Rhea)
- **URL**: https://artemis.meetrhea.com
- **Database**: PostgreSQL on Coolify (TBD - needs manual creation)
- **Deployed via**: Coolify (app uuid: `t8o840kw8sgoscog4w444ccg`)
- **SSO**: Rhea SSO at https://login.meetrhea.com

### Fork Relationship
This is a fork of `aic-holdings/artemis`. It can evolve independently:
- `origin` -> `meetrhea/artemis` (push changes here)
- `upstream` -> `aic-holdings/artemis` (pull upstream updates when needed)

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
  models.py        # SQLAlchemy models
  database.py      # DB connection
  routers/         # Route handlers
    whisper.py     # Whisper audio transcription
    proxy_routes.py # LLM API proxy
  services/        # Business logic
  templates/       # Jinja2 HTML templates
  static/          # CSS, JS assets
```

### Running Seed Data

```bash
python scripts/seed_data.py
```

This creates test users, organizations, groups, API keys, and usage data.
