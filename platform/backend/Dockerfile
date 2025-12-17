# Vision AI Platform Backend
# Build: docker build -t vision-backend:latest .
# Run: docker run -p 8000:8000 --env-file .env vision-backend:latest

ARG REGISTRY_MIRROR=

FROM ${REGISTRY_MIRROR}python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (for better caching)
COPY pyproject.toml .

# Install dependencies using uv (much faster than pip)
RUN uv pip install --system --no-cache -r pyproject.toml

# ============================================
# Production Stage
# ============================================
FROM ${REGISTRY_MIRROR}python:3.11-slim AS production

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY app/ ./app/
COPY start.sh .
COPY migrations/ ./migrations/

# Copy sample datasets (shared via volume in production)
COPY sample_datasets/ /app/datasets/

# Note: Training code is NOT copied to Backend (proper dependency isolation)
# Backend communicates with Training Services via HTTP API for all training-related operations:
# - Model registry: GET /models/list, GET /models/{name}
# - Config schema: GET /config-schema?framework=X&task_type=Y
# - Training execution: POST /training/start
# This maintains clean separation between Backend (API/DB) and Training (ML)

# Create necessary directories
RUN mkdir -p /app/outputs /app/uploads /app/data/outputs /app/data/logs /app/mlruns

# Make start script executable
RUN chmod +x start.sh

# Create non-root user for security
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser && \
    chown -R appuser:appuser /app

USER appuser

# Expose ports
EXPOSE 8000
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start both MLflow server and FastAPI application
CMD ["./start.sh"]
