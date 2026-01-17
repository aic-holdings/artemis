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

# Skip alembic on startup to avoid revision overlap issues.
# Use POST /api/migrate endpoint with MASTER_API_KEY instead.
echo "Note: Migrations are handled via /api/migrate endpoint"
echo "Call: curl -X POST https://artemis.jettaintelligence.com/api/migrate -H 'Authorization: Bearer \$MASTER_API_KEY'"

# Show current alembic state for debugging
CURRENT=$(alembic current 2>&1)
echo "Current alembic state: $CURRENT"

echo "Final alembic state:"
alembic current 2>&1

echo "Starting Artemis server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
