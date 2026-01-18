#!/bin/bash

echo "=== Artemis Startup ==="
echo "DATABASE_URL is set: $(if [ -n "$DATABASE_URL" ]; then echo 'yes'; else echo 'NO!'; fi)"

echo "Running database migrations..."

# Skip alembic on startup to avoid revision overlap issues.
# Use POST /api/migrate endpoint with MASTER_API_KEY instead.
echo "Note: Migrations are handled via /api/migrate endpoint"
echo "Call: curl -X POST https://artemis.jettaintelligence.com/api/migrate -H 'Authorization: Bearer \$MASTER_API_KEY'"

# Show current alembic state for debugging
CURRENT=$(alembic current 2>&1)
echo "Current alembic state: $CURRENT"

echo "Starting Artemis server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
