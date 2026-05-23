# ─────────────────────────────────────────────────────────────────────────────
# AIOS Docker Image
# Multi-stage build: deps → runtime
# ─────────────────────────────────────────────────────────────────────────────

# Stage 1: dependency builder
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Stage 2: runtime image
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="AIOS"
LABEL org.opencontainers.image.description="Agentic AI Operating System"
LABEL org.opencontainers.image.version="0.1.0"

# Create non-root user
RUN groupadd -r aios && useradd -r -g aios aios

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy source code
COPY src/ ./src/
COPY evaluation/ ./evaluation/
COPY configs/ ./configs/
COPY pyproject.toml .

# Set permissions
RUN chown -R aios:aios /app

USER aios

# Runtime environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    AIOS_ENV=production \
    LOG_LEVEL=INFO

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/v1/health')"

CMD ["uvicorn", "src.gateway.app:create_app", \
     "--factory", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--log-config", "configs/log_config.json"]
