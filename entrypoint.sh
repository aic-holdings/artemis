#!/bin/bash

echo "=== Artemis Startup ==="
echo "DATABASE_URL is set: $(if [ -n "$DATABASE_URL" ]; then echo 'yes'; else echo 'NO!'; fi)"

echo "Running database migrations..."
alembic upgrade head 2>&1 || echo "WARNING: Migration command returned error"

echo "Checking alembic current version..."
alembic current 2>&1 || echo "WARNING: Could not get current version"

echo "Starting Artemis server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
