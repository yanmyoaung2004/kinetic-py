FROM python:3.13-slim AS builder

WORKDIR /app

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# ── Runtime ────────────────────────────────────────────
FROM python:3.13-slim

WORKDIR /app

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY src/ src/
COPY config/ config/
COPY pyproject.toml README.md ./

# Create data directories
RUN mkdir -p agents_workspace agent_sandbox

VOLUME ["/app/config", "/app/agents_workspace", "/app/agent_sandbox"]

EXPOSE 18789

ENV HIDE_CONSOLE=1
ENV API_PORT=18789

ENTRYPOINT ["kinetic"]
