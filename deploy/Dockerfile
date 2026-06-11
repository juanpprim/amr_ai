# AMR Learning Agent — hardened image used by both Fly.io and Railway.
#
# Adds on top of the bare Streamlit container:
#   - nginx for security headers, rate limiting, and WebSocket proxy
#   - OAuth2 Proxy for Auth0 OIDC authentication (optional, auto-detected)
#   - Basic auth fallback via htpasswd (when OAuth2 secrets not set)
#   - entrypoint.sh to run nginx + (optionally) oauth2-proxy + Streamlit
#
# Platform configs live next to this file:
#   - deploy/fly.toml              (Fly.io)
#   - deploy/cloudrun-service.yaml (Cloud Run)
#   - Railway: point service Build → Dockerfile at deploy/Dockerfile
#
# Build locally:
#   docker build -f deploy/Dockerfile -t amr-ai .
#   docker run --rm -p 8080:8080 \
#       -e OPENAI_API_KEY=... \
#       -e AMR_AUTH_PASSWORD=changeme \
#       amr-ai
#
# ---------------------------------------------------------------------------
# Builder: compile chroma-hnswlib (no py3.13 wheel on PyPI yet)
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Runtime image — nginx + (optional) oauth2-proxy + Streamlit
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime packages: curl (healthcheck) + nginx (reverse proxy) + openssl (htpasswd)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        nginx \
        openssl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# OAuth2 Proxy binary (Auth0 OIDC authentication)
# Used when AUTH0_* secrets are set; otherwise ignored (basic auth fallback).
# ---------------------------------------------------------------------------
ARG OAUTH2_PROXY_VERSION=v7.9.0
RUN curl -fsSL "https://github.com/oauth2-proxy/oauth2-proxy/releases/download/${OAUTH2_PROXY_VERSION}/oauth2-proxy-${OAUTH2_PROXY_VERSION}.linux-amd64.tar.gz" \
    | tar -xz --strip-components=1 -C /usr/local/bin/ \
       "oauth2-proxy-${OAUTH2_PROXY_VERSION}.linux-amd64/oauth2-proxy" \
    && chmod +x /usr/local/bin/oauth2-proxy

# ---------------------------------------------------------------------------
# nginx configuration
# ---------------------------------------------------------------------------
COPY deploy/nginx.conf /etc/nginx/nginx.conf

# Create writable dirs for nginx workers (drop from root to www-data)
# and default auth.conf (entrypoint may override at runtime).
RUN mkdir -p /var/cache/nginx /var/run \
    && chown -R www-data:www-data /var/cache/nginx /var/run \
    && touch /etc/nginx/.htpasswd \
    && printf 'auth_basic           "AMR Learning Agent";\nauth_basic_user_file /etc/nginx/.htpasswd;\n' \
       > /etc/nginx/auth.conf \
    && mkdir -p /etc/oauth2-proxy

# ---------------------------------------------------------------------------
# App user — matches HF Spaces convention but nginx needs root to bind
# We run the entrypoint as root (nginx master needs it), but:
#   - nginx workers drop to www-data
#   - Streamlit runs as user via the entrypoint
# ---------------------------------------------------------------------------
RUN useradd --create-home --uid 1000 --shell /bin/bash user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    XDG_CACHE_HOME=/home/user/.cache

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

# ---------------------------------------------------------------------------
# App source (vectors live in Chroma Cloud — no bundled DB)
# ---------------------------------------------------------------------------
COPY src/ ./src/
COPY app.py ./app.py
COPY robots.txt ./robots.txt

# Make the virtualenv the default Python and expose src/ for imports
ENV VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app

# Streamlit config — headless, on internal port (nginx proxies from 8080)
ENV STREAMLIT_SERVER_PORT=7860 \
    STREAMLIT_SERVER_ADDRESS=127.0.0.1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=true

# ---------------------------------------------------------------------------
# Entrypoint: runs nginx + (optionally) OAuth2 Proxy + Streamlit
# ---------------------------------------------------------------------------
COPY deploy/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Give app user ownership of the app directory
RUN chown -R user:user /app

# nginx listens on 8080 (public), Streamlit on 7860 (internal)
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD curl --fail http://localhost:8080/_stcore/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
