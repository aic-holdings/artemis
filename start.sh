#!/bin/bash
# Start Artemis server

# Default port from config (can be overridden with PORT env var)
PORT=${PORT:-8767}

# Kill any existing process on the port
fuser -k $PORT/tcp 2>/dev/null || true
sleep 1

# Activate venv and start server
source venv/bin/activate
LOCALHOST_MODE=true uvicorn app.main:app --reload --port $PORT
