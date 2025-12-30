#!/bin/bash
set -e

echo "=== Artemis Startup ==="
echo "Running database migrations..."

if alembic upgrade head; then
    echo "Migrations completed successfully"
else
    echo "WARNING: Migration failed, but continuing..."
fi

echo "Starting Artemis server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
