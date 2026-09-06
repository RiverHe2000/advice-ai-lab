# The collector image: FastAPI ingest/query API with the SQLite store and the Prometheus
# exporter. Non-root, CPU-only, no model weights.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PYTHONUTF8=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY slos ./slos
COPY prompts ./prompts
RUN pip install --no-cache-dir ".[serve]" \
    && useradd --create-home --uid 10001 opsloop \
    && mkdir -p /data && chown -R opsloop:opsloop /data /app
USER opsloop
VOLUME ["/data"]
EXPOSE 8090
ENTRYPOINT []
CMD ["opsloop", "--store", "/data/traces.sqlite", "serve", "--host", "0.0.0.0", "--port", "8090"]
