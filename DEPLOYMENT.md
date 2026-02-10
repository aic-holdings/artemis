# Artemis Deployment Guide

Artemis is deployed to **Coolify** on the AIC server infrastructure.

---

## Infrastructure Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     AIC Server Infrastructure                    │
│                     (hostkey-server repo)                        │
│                                                                  │
│  Coolify (hq.jettaintelligence.com)                             │
│  ├── Manages deployments, SSL, routing                          │
│  ├── GitHub App: aic-holdings org access                        │
│  └── Traefik proxy on ports 80/443                              │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐      ┌─────────────────┐                   │
│  │    Artemis      │      │   artemis-db    │                   │
│  │  (this repo)    │─────▶│  (PostgreSQL)   │                   │
│  │                 │      │                 │                   │
│  │ Port: 8000      │      │ Port: 5432      │                   │
│  │ Build: Docker   │      │ Managed by      │                   │
│  │                 │      │ Coolify         │                   │
│  └─────────────────┘      └─────────────────┘                   │
│         │                                                        │
│         ▼                                                        │
│  https://artemis.jettaintelligence.com                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Deploy

```bash
# Get Coolify token from: https://hq.jettaintelligence.com/security/api-tokens
COOLIFY_TOKEN=xxx ./scripts/coolify/deploy.sh
```

This script will:
1. Check if `artemis-db` PostgreSQL exists, create if not
2. Create or update the Artemis application
3. Link app to database via environment variables
4. Trigger deployment

---

## Manual Deployment Steps

If you prefer manual setup via Coolify UI:

### 1. Database (if not exists)

1. Go to **Projects** → **AIC Apps** → **production**
2. Click **+ New** → **Database** → **PostgreSQL**
3. Configure:
   - Name: `artemis-db`
   - User: `artemis`
   - Password: `artemis_prod_2024`
   - Database: `artemis`
4. Deploy and wait for healthy status

### 2. Application

1. Go to **Projects** → **AIC Apps** → **production**
2. Click **+ New** → **Application** → **GitHub** (select aic-holdings app)
3. Select repository: `aic-holdings/artemis`
4. Configure:
   - Branch: `main`
   - Build Pack: `Dockerfile`
   - Port: `8000`
   - Domain: `https://artemis.jettaintelligence.com`

### 3. Environment Variables

In the application settings, add:

| Variable | Value | Notes |
|----------|-------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://artemis:artemis_prod_2024@DBCONTAINER:5432/artemis` | Replace DBCONTAINER with db container name |
| `SECRET_KEY` | (generate secure random) | `openssl rand -hex 32` |
| `ENCRYPTION_KEY` | (generate secure random) | `openssl rand -hex 32` |
| `JWT_ALGORITHM` | `HS256` | |
| `JWT_EXPIRATION_HOURS` | `24` | |

### 4. DNS

Artemis is deployed on Railway (project: amusing-generosity). DNS is managed via Railway's custom domain feature — no manual A record needed. The old Coolify deployment on `80.209.241.157` is deprecated.

---

## Resource IDs

These are used by the deploy script and referenced in hostkey-server docs:

| Resource | UUID | Notes |
|----------|------|-------|
| Coolify Server | `pwkck048sooogwk804c04cko` | localhost |
| AIC Apps Project | `jokw0ssk0kckok4c8o0ko0gs` | |
| GitHub App | `ow0gw0840008okgo44cwsk4w` | aic-holdings org |
| artemis-db | `wkcskwwo8skoo0g00s080koo` | PostgreSQL |
| artemis (app) | (created on deploy) | |

---

## Database Connection

### From Artemis Container

```
DATABASE_URL=postgresql+asyncpg://artemis:artemis_prod_2024@wkcskwwo8skoo0g00s080koo:5432/artemis
```

The container name (`wkcskwwo8skoo0g00s080koo`) is the database UUID. Coolify's internal Docker network allows containers to reach each other by name.

### Direct Access (for debugging)

```bash
# From the server
sudo docker exec -it wkcskwwo8skoo0g00s080koo psql -U artemis -d artemis
```

---

## Secrets Management

**Never commit secrets to git.** The following must be set in Coolify UI:

- `SECRET_KEY` - Used for session signing
- `ENCRYPTION_KEY` - Used for encrypting provider API keys

Generate with:
```bash
openssl rand -hex 32
```

---

## Updating

### Via Git Push (Automatic)

Push to `main` branch triggers automatic deployment via GitHub webhook.

### Via Railway (Manual)

```bash
# Artemis is now on Railway (project: amusing-generosity)
# Redeploy via Railway CLI or dashboard
railway redeploy
```

---

## Troubleshooting

### Check Application Logs

```bash
# Via Coolify UI
# Go to application → Logs

# Or via Docker
sudo docker logs CONTAINER_NAME -f
```

### Check Database Connection

```bash
# Test from server
sudo docker exec wkcskwwo8skoo0g00s080koo pg_isready -U artemis
```

### Reset Database

**Warning: This deletes all data!**

```bash
sudo docker exec wkcskwwo8skoo0g00s080koo psql -U artemis -d postgres -c "DROP DATABASE artemis;"
sudo docker exec wkcskwwo8skoo0g00s080koo psql -U artemis -d postgres -c "CREATE DATABASE artemis;"
# App will recreate tables on next start
```

---

## Related Documentation

- **Infrastructure Setup:** `hostkey-server/docs/COOLIFY_OPERATIONS.md`
- **Migration History:** `hostkey-server/docs/COOLIFY_MIGRATION.md`
- **DNS Management:** `hostkey-server/scripts/dns/route53-manage.sh`
- **Session Learnings:** `hostkey-server/docs/SESSION_LEARNINGS_2025-12-09.md`

---

## Architecture Decisions

### Why Separate Database?

The database is managed as a separate Coolify resource (not bundled in docker-compose) because:

1. **Data outlives code** - Database survives app redeployments
2. **Independent lifecycle** - Can backup/restore without touching app
3. **Visibility** - Coolify UI shows database status, connections
4. **Shareable** - Other apps can connect if needed

### Why Coolify?

See `hostkey-server/docs/COOLIFY_MIGRATION.md` for the full rationale. TL;DR:
- Self-hosted PaaS (no vendor lock-in)
- Handles SSL, routing, deployments
- API enables automation
- MCP server enables AI-assisted management
