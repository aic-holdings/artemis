#!/bin/bash

echo "=== Artemis Startup ==="
echo "DATABASE_URL is set: $(if [ -n "$DATABASE_URL" ]; then echo 'yes'; else echo 'NO!'; fi)"

# Start Ollama in background
echo "Starting Ollama server..."
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be ready
echo "Waiting for Ollama to start..."
for i in {1..30}; do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "Ollama is ready!"
        break
    fi
    sleep 1
done

# Pull embedding model if not present
echo "Checking for nomic-embed-text model..."
if ! ollama list | grep -q "nomic-embed-text"; then
    echo "Pulling nomic-embed-text model (this may take a few minutes on first run)..."
    ollama pull nomic-embed-text
else
    echo "nomic-embed-text model already available"
fi

echo "Running database migrations..."

# Latest migration revision
LATEST_REVISION="d4e5f6g7h8i9"

# Check current alembic state
CURRENT=$(alembic current 2>&1)
echo "Current alembic state: $CURRENT"

# If already at the latest revision, skip
if echo "$CURRENT" | grep -q "$LATEST_REVISION"; then
    echo "Already at latest revision ($LATEST_REVISION), no migrations needed"
elif echo "$CURRENT" | grep -q "(head)"; then
    echo "Already at head, no migrations needed"
else
    # Try explicit upgrade to latest revision (avoids head resolution issues)
    echo "Upgrading to $LATEST_REVISION..."
    UPGRADE_RESULT=$(alembic upgrade "$LATEST_REVISION" 2>&1)

    if echo "$UPGRADE_RESULT" | grep -q "DuplicateTable\|already exists"; then
        echo "Tables exist but need alembic stamp. Checking current schema..."
        # Check if is_service_account column exists
        if echo "$CURRENT" | grep -q "c3d4e5f6g7h8"; then
            echo "At c3d4e5f6g7h8, stamping and upgrading..."
            alembic upgrade "$LATEST_REVISION" 2>&1
        else
            echo "Stamping to latest and retrying..."
            alembic stamp "$LATEST_REVISION" 2>&1
        fi
    elif echo "$UPGRADE_RESULT" | grep -q "overlaps"; then
        echo "Revision overlap detected, using +1 relative upgrade..."
        alembic upgrade +1 2>&1
    else
        echo "$UPGRADE_RESULT"
    fi
fi

echo "Final alembic state:"
alembic current 2>&1

echo "Starting Artemis server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
