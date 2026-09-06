# syntax=docker/dockerfile:1.7
# Multi-stage: build a venv with the package, ship it on a slim runtime as a non-root user.
# Build from the project root:  docker build -f deploy/Dockerfile -t filenote/app:0.1.0 .

FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir ".[serve]"

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    FILENOTE_WEB__HOST=0.0.0.0 \
    FILENOTE_WEB__PORT=8080 \
    FILENOTE_DB_PATH=/data/drafts.sqlite \
    FILENOTE_AUDIT_PATH=/data/audit.jsonl \
    FILENOTE_MODEL__KIND=fake
RUN groupadd --system app && useradd --system --gid app --home /app app \
 && mkdir -p /data /app && chown -R app:app /data /app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
USER app
EXPOSE 8080
# No curl on the slim image: the check is a tiny Python one-liner against /health.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2); sys.exit(0 if r.status==200 else 1)"
CMD ["filenote", "serve"]
