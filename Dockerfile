FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make entrypoint executable and create non-root user
RUN chmod +x entrypoint.sh && useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Run entrypoint (migrations + server)
ENTRYPOINT ["./entrypoint.sh"]
