# ── Stage 1: dependency builder ────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Speed: bytecode compilation + copy mode (no symlinks — safe across layers)
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install deps first (layer cache: only invalidated when pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy full source (after deps to maximise layer cache hits)
COPY . .

# Install project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ── Stage 2: minimal runtime image ─────────────────────────────────────────────
FROM python:3.12-slim AS runner

# Non-root user for security
RUN addgroup --system --gid 1001 appgroup \
 && adduser  --system --uid 1001 --ingroup appgroup appuser

WORKDIR /app

# Copy only what's needed from builder
COPY --from=builder --chown=appuser:appgroup /app /app

# Runtime env defaults (overridden by Cloud Run env vars / Secret Manager mounts)
ENV PATH="/app/.venv/bin:$PATH" \
    HOST="0.0.0.0" \
    PORT="8080" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1"

USER appuser

EXPOSE 8080

# Cloud Run sets $PORT; uvicorn reads it
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
