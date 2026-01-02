FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including curl for Ollama install
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Expose ports (8000 for FastAPI, 11434 for Ollama)
EXPOSE 8000 11434

# Run entrypoint (starts Ollama + migrations + server)
ENTRYPOINT ["./entrypoint.sh"]
