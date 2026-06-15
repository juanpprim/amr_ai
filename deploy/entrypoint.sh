#!/usr/bin/env bash
# Entrypoint (Fly.io / Railway): runs nginx + (optionally) OAuth2 Proxy + Streamlit.
#
# Auth modes (auto-detected from environment):
#   1. OAuth2 OIDC (Auth0): AUTH0_DOMAIN + AUTH0_CLIENT_ID + AUTH0_CLIENT_SECRET
#   2. Basic auth:          AMR_AUTH_PASSWORD or baked-in .htpasswd
#   3. No auth configured:  FATAL — container refuses to start
#
# Ports:
#   nginx         :8080  (public, reverse proxy + security headers)
#   oauth2-proxy  :4180  (internal, OIDC handler — only in OAuth2 mode)
#   streamlit     :7860  (internal, app)

set -euo pipefail

echo "=== AMR Learning Agent ==="
echo "  nginx     → :8080 (public)"
echo "  streamlit → :7860 (internal)"

# ── Signal handling for graceful shutdown ────────────────────────
NGINX_PID=""
OAUTH2_PROXY_PID=""
STREAMLIT_PID=""

cleanup() {
    echo "Caught signal — shutting down..."
    kill -TERM ${NGINX_PID} ${OAUTH2_PROXY_PID} ${STREAMLIT_PID} 2>/dev/null || true
    wait ${NGINX_PID} ${OAUTH2_PROXY_PID} ${STREAMLIT_PID} 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT SIGQUIT

# ── Validate required environment ────────────────────────────────
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "WARNING: OPENAI_API_KEY is not set!"
    echo "  The agent will fail when a user sends a message."
    echo "  Set it with: fly secrets set OPENAI_API_KEY=sk-..."
fi

# ── Auth mode detection (fail-closed) ───────────────────────────
AUTH_MODE=""

if [ -n "${AUTH0_DOMAIN:-}" ] && [ -n "${AUTH0_CLIENT_ID:-}" ] && [ -n "${AUTH0_CLIENT_SECRET:-}" ]; then
    AUTH_MODE="oauth2"
elif [ -n "${AMR_AUTH_PASSWORD:-}" ]; then
    AUTH_MODE="basic"
elif [ -f /etc/nginx/.htpasswd ] && [ -s /etc/nginx/.htpasswd ]; then
    AUTH_MODE="basic"
else
    echo ""
    echo "FATAL: No authentication configured!"
    echo ""
    echo "  The container will NOT start without auth to prevent"
    echo "  exposing the app (and your OpenAI API key) to the internet."
    echo ""
    echo "  Option 1 — Auth0 OIDC (recommended for multi-user):"
    echo "    fly secrets set AUTH0_DOMAIN=yourteam.auth0.com"
    echo "    fly secrets set AUTH0_CLIENT_ID=your-client-id"
    echo "    fly secrets set AUTH0_CLIENT_SECRET=your-client-secret"
    echo "    fly secrets set OAUTH2_PROXY_COOKIE_SECRET=\$(openssl rand -base64 32)"
    echo "    fly secrets set PUBLIC_HOSTNAME=amr-learning-agent.fly.dev"
    echo ""
    echo "  Option 2 — Basic auth (quick single-user):"
    echo "    fly secrets set AMR_AUTH_PASSWORD=your-secure-password"
    echo ""
    exit 1
fi

# ── OAuth2 OIDC mode (Auth0) ───────────────────────────────────
if [ "$AUTH_MODE" = "oauth2" ]; then
    echo "  auth mode → OAuth2 OIDC (Auth0)"
    echo "  auth0     → ${AUTH0_DOMAIN}"

    # Validate additional required secrets
    if [ -z "${OAUTH2_PROXY_COOKIE_SECRET:-}" ]; then
        echo "FATAL: OAUTH2_PROXY_COOKIE_SECRET is not set!"
        echo "  Generate with: openssl rand -base64 32"
        echo "  Set with: fly secrets set OAUTH2_PROXY_COOKIE_SECRET=<value>"
        exit 1
    fi
    if [ -z "${PUBLIC_HOSTNAME:-}" ]; then
        echo "FATAL: PUBLIC_HOSTNAME is not set!"
        echo "  Set with: fly secrets set PUBLIC_HOSTNAME=amr-learning-agent.fly.dev"
        exit 1
    fi

    # Build email allowlist file (if provided)
    EMAILS_FLAG=""
    if [ -n "${OAUTH2_ALLOWED_EMAILS:-}" ]; then
        echo "${OAUTH2_ALLOWED_EMAILS}" | tr ',' '\n' > /etc/oauth2-proxy/allowed-emails.txt
        EMAILS_FLAG="--authenticated-emails-file=/etc/oauth2-proxy/allowed-emails.txt"
        USERS=$(wc -l < /etc/oauth2-proxy/allowed-emails.txt)
        echo "  allowlist → ${USERS} emails"
    fi

    # Email domain restriction (if provided). Skip when using an allowlist file —
    # oauth2-proxy requires either --email-domain or --authenticated-emails-file.
    DOMAIN_FLAG=""
    if [ -z "${OAUTH2_ALLOWED_EMAILS:-}" ]; then
        DOMAIN_FLAG="--email-domain=*"
        if [ -n "${OAUTH2_EMAIL_DOMAIN:-}" ]; then
            DOMAIN_FLAG="--email-domain=${OAUTH2_EMAIL_DOMAIN}"
            echo "  domains   → ${OAUTH2_EMAIL_DOMAIN}"
        fi
    fi

    # Generate nginx auth.conf for OAuth2 mode
    cat > /etc/nginx/auth.conf <<'AUTHCONF'
auth_request /oauth2/auth;
auth_request_set $auth_user $upstream_http_x_auth_request_user;
auth_request_set $auth_email $upstream_http_x_auth_request_email;
error_page 401 = @oauth2_signin;
AUTHCONF

    # Start oauth2-proxy
    echo "  oauth2    → :4180 (internal)"
    oauth2-proxy \
        --provider=oidc \
        --oidc-issuer-url="https://${AUTH0_DOMAIN}/" \
        --client-id="${AUTH0_CLIENT_ID}" \
        --client-secret="${AUTH0_CLIENT_SECRET}" \
        --redirect-url="https://${PUBLIC_HOSTNAME}/oauth2/callback" \
        --cookie-secret="${OAUTH2_PROXY_COOKIE_SECRET}" \
        --cookie-secure=true \
        --cookie-httponly=true \
        --cookie-samesite=lax \
        --http-address=127.0.0.1:4180 \
        --reverse-proxy=true \
        --insecure-oidc-allow-unverified-email=true \
        --whitelist-domain="${PUBLIC_HOSTNAME}" \
        --pass-user-headers=true \
        --set-xauthrequest=true \
        --request-logging=true \
        --silence-ping-logging=true \
        ${DOMAIN_FLAG} \
        ${EMAILS_FLAG} &
    OAUTH2_PROXY_PID=$!
fi

# ── Basic auth mode ─────────────────────────────────────────────
if [ "$AUTH_MODE" = "basic" ]; then
    if [ -n "${AMR_AUTH_PASSWORD:-}" ]; then
        AMR_USER="${AMR_AUTH_USER:-admin}"
        echo "  auth mode → basic auth (single-user from secret)"
        echo "  auth user → ${AMR_USER}"
        HASH=$(openssl passwd -apr1 "${AMR_AUTH_PASSWORD}")
        echo "${AMR_USER}:${HASH}" > /etc/nginx/.htpasswd
    else
        USERS=$(wc -l < /etc/nginx/.htpasswd)
        echo "  auth mode → basic auth (.htpasswd baked in, ${USERS} users)"
    fi

    # Generate nginx auth.conf for basic auth mode
    cat > /etc/nginx/auth.conf <<'AUTHCONF'
auth_basic           "AMR Learning Agent";
auth_basic_user_file /etc/nginx/.htpasswd;
AUTHCONF
fi

# ── Start nginx ─────────────────────────────────────────────────
nginx -g 'daemon off;' &
NGINX_PID=$!

# ── Start Streamlit as non-root user ────────────────────────────
su -s /bin/bash user -c "streamlit run app.py" &
STREAMLIT_PID=$!

echo "  nginx PID     → ${NGINX_PID}"
if [ -n "${OAUTH2_PROXY_PID}" ]; then
    echo "  oauth2 PID    → ${OAUTH2_PROXY_PID}"
fi
echo "  streamlit PID → ${STREAMLIT_PID}"
echo "=== Ready ==="

# ── Wait for any process to exit ────────────────────────────────
# Build the list of PIDs to wait on (2 or 3 depending on auth mode)
PIDS="${NGINX_PID} ${STREAMLIT_PID}"
if [ -n "${OAUTH2_PROXY_PID}" ]; then
    PIDS="${PIDS} ${OAUTH2_PROXY_PID}"
fi

wait -n ${PIDS} 2>/dev/null
EXIT_CODE=$?

echo "Process exited with code ${EXIT_CODE} — shutting down..."
kill ${PIDS} 2>/dev/null || true
exit "${EXIT_CODE}"
