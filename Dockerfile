# syntax=docker/dockerfile:1
# ── Stage 1: builder ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Build-time arg to install optional extras (e.g. "rag,uil"); empty = none.
ARG INSTALL_EXTRAS=""

WORKDIR /build

# System build deps (needed by some Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create a venv so the runtime stage can copy it cleanly.
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install project deps into the venv.
COPY pyproject.toml ./
COPY adapters/ ./adapters/
COPY api/ ./api/
COPY observability/ ./observability/
COPY pipeline/ ./pipeline/
COPY prompts/ ./prompts/
COPY schemas/ ./schemas/
COPY tools/ ./tools/
COPY worker/ ./worker/
COPY profile_analyst.py ./

# Core install; append optional extras if provided.
RUN if [ -n "$INSTALL_EXTRAS" ]; then \
        pip install --no-cache-dir ".[${INSTALL_EXTRAS}]"; \
    else \
        pip install --no-cache-dir .; \
    fi

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user (UID 10001) — never run as root in production.
RUN groupadd --gid 10001 appgroup \
    && useradd --uid 10001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy the venv from builder.
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"
# Make /app source (worker/, profile_analyst.py, and the patched pipeline) importable for every
# role (api, worker, CLI) and take precedence over the installed copy.
ENV PYTHONPATH="/app"

# Copy application source.
COPY --from=builder /build/ .

# Copy the entrypoint script and make it executable.
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

# projects/ is always a bind mount from the host (artifacts, GDPR erase/gc).
VOLUME /app/projects

# Switch to non-root user.
USER appuser

ENTRYPOINT ["/app/docker/entrypoint.sh"]
