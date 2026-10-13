# Build from the repository root: docker build -f server/Dockerfile .
# Review/update these exact tags and build-tool pins with security releases.
FROM python:3.12.15-slim-bookworm AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY server/ ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir setuptools==78.1.0 wheel==0.45.1 \
    && /opt/venv/bin/pip install --no-cache-dir --no-build-isolation .

FROM python:3.12.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/server \
    PATH=/opt/venv/bin:$PATH
RUN groupadd --gid 10001 powerk \
    && useradd --uid 10001 --gid 10001 --no-log-init --no-create-home powerk \
    && mkdir -p /data /app/tools /app/deploy/scripts \
    && chown 10001:10001 /data
COPY --from=build /opt/venv /opt/venv
# Prefer source over site-packages: api.py's parents[2] must resolve to /app.
COPY server/powerk/ /app/server/powerk/
COPY tools/provision.py /app/tools/provision.py
COPY deploy/scripts/entrypoint.py /app/deploy/scripts/entrypoint.py
WORKDIR /app/server
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8080 10086
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import http.client; c=http.client.HTTPConnection('127.0.0.1',8080,timeout=3); c.request('GET','/'); r=c.getresponse(); raise SystemExit(0 if r.status < 500 else 1)"
ENTRYPOINT ["python", "/app/deploy/scripts/entrypoint.py"]
