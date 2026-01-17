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
    # Try to run alembic upgrade
    echo "Attempting alembic upgrade..."
    UPGRADE_RESULT=$(alembic upgrade "$LATEST_REVISION" 2>&1)
    echo "$UPGRADE_RESULT"

    # If alembic fails due to overlap issues, apply the migration manually
    if echo "$UPGRADE_RESULT" | grep -q "overlaps\|failed"; then
        echo "Alembic overlap detected, applying migration manually via SQL..."

        # Check if is_service_account column exists
        COLUMN_CHECK=$(python3 -c "
import os
import asyncio
from sqlalchemy import create_engine, text

db_url = os.environ.get('DATABASE_URL', '').replace('+asyncpg', '')
if not db_url:
    print('NO_DB_URL')
    exit(0)

engine = create_engine(db_url)
with engine.connect() as conn:
    result = conn.execute(text('''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'is_service_account'
    '''))
    if result.fetchone():
        print('EXISTS')
    else:
        print('MISSING')
" 2>&1)

        echo "Column check result: $COLUMN_CHECK"

        if [ "$COLUMN_CHECK" = "MISSING" ]; then
            echo "Adding is_service_account column..."
            python3 -c "
import os
from sqlalchemy import create_engine, text

db_url = os.environ.get('DATABASE_URL', '').replace('+asyncpg', '')
engine = create_engine(db_url)
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE users ADD COLUMN is_service_account BOOLEAN NOT NULL DEFAULT false'))
    conn.commit()
print('Column added successfully')
" 2>&1

            # Update alembic version
            echo "Updating alembic version to $LATEST_REVISION..."
            alembic stamp "$LATEST_REVISION" 2>&1
        elif [ "$COLUMN_CHECK" = "EXISTS" ]; then
            echo "Column already exists, just stamping alembic..."
            alembic stamp "$LATEST_REVISION" 2>&1
        else
            echo "Could not check column: $COLUMN_CHECK"
        fi
    fi
fi

echo "Final alembic state:"
alembic current 2>&1

echo "Starting Artemis server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
