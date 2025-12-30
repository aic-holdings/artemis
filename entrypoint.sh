#!/bin/bash

echo "=== Artemis Startup ==="
echo "DATABASE_URL is set: $(if [ -n "$DATABASE_URL" ]; then echo 'yes'; else echo 'NO!'; fi)"

echo "Running database migrations..."

# Check current alembic state
CURRENT=$(alembic current 2>&1)
echo "Current alembic state: $CURRENT"

# If no version tracked but tables exist, stamp to the last known good version
if echo "$CURRENT" | grep -q "head"; then
    echo "Already at head, no migrations needed"
elif echo "$CURRENT" | grep -q "(head)"; then
    echo "Already at head, no migrations needed"
elif echo "$CURRENT" | grep -q "c3d4e5f6g7h8"; then
    echo "At c3d4e5f6g7h8, running upgrade..."
    alembic upgrade head 2>&1
else
    # Try upgrade first
    echo "Attempting upgrade..."
    UPGRADE_RESULT=$(alembic upgrade head 2>&1)

    if echo "$UPGRADE_RESULT" | grep -q "DuplicateTable\|already exists"; then
        echo "Tables exist but alembic version not set. Stamping to c3d4e5f6g7h8..."
        alembic stamp c3d4e5f6g7h8 2>&1
        echo "Now upgrading to head..."
        alembic upgrade head 2>&1
    else
        echo "$UPGRADE_RESULT"
    fi
fi

echo "Final alembic state:"
alembic current 2>&1

echo "Starting Artemis server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
