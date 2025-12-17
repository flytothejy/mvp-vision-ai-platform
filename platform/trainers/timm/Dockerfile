# Timm (PyTorch Image Models) Trainer
# Build: docker build -t trainer-timm:latest .
# Run: docker run --env-file .env trainer-timm:latest python train.py --job-id 123 ...
#
# For GPU support, use NVIDIA base image:
# docker build -f Dockerfile.gpu -t trainer-timm:gpu .

ARG REGISTRY_MIRROR=

# ============================================
# Builder Stage
# ============================================
FROM ${REGISTRY_MIRROR}python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (for better caching)
COPY pyproject.toml .

# Install all dependencies including export extras using uv
RUN uv pip install --system --no-cache ".[export]"

# ============================================
# Production Stage
# ============================================
FROM ${REGISTRY_MIRROR}python:3.11-slim AS production

WORKDIR /app

# Install runtime dependencies for OpenCV and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-dev \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy all trainer code
COPY *.py ./
COPY capabilities.json .

# Create directories for data and outputs
RUN mkdir -p /app/data /app/outputs /app/checkpoints

# Create non-root user for security
RUN groupadd --gid 1000 trainer && \
    useradd --uid 1000 --gid trainer --shell /bin/bash --create-home trainer && \
    chown -R trainer:trainer /app

USER trainer

# Environment settings
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check (for Kubernetes readiness probe)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import timm; print('OK')" || exit 1

# Default command (can be overridden)
CMD ["python", "train.py", "--help"]
