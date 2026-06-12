#!/usr/bin/env bash
# Deploy AMR Learning Agent to Fly.io.
#
# Same image as Railway: nginx + oauth2-proxy (Auth0 OIDC) + Streamlit,
# with Chroma Cloud as the vector store.
#
# Prerequisites:
#   1. Install flyctl: curl -L https://fly.io/install.sh | sh
#   2. Authenticate:   fly auth login
#
# First-time setup (run once):
#   ./scripts/deploy_fly.sh --init
#
# Subsequent deploys:
#   ./scripts/deploy_fly.sh
#
# Recommended auth (multi-user via Auth0):
#   fly secrets set AUTH0_DOMAIN=... AUTH0_CLIENT_ID=... AUTH0_CLIENT_SECRET=...
#   fly secrets set OAUTH2_PROXY_COOKIE_SECRET=$(openssl rand -base64 32)
#   fly secrets set PUBLIC_HOSTNAME=amr-learning-agent.fly.dev
#   fly secrets set OAUTH2_ALLOWED_EMAILS=a@x.com,b@y.com
#
# Single-user fallback:
#   fly secrets set AMR_AUTH_PASSWORD=your-secure-password

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FLY_TOML="$PROJECT_DIR/deploy/fly.toml"

if ! command -v fly &>/dev/null; then
    echo "ERROR: flyctl not found. Install: curl -L https://fly.io/install.sh | sh"
    exit 1
fi

# ── First-time init ──────────────────────────────────────────────
if [ "${1:-}" = "--init" ]; then
    echo "=== First-time Fly.io setup ==="

    # Copy fly.toml to project root (Fly expects it there)
    cp "$FLY_TOML" "$PROJECT_DIR/fly.toml"
    echo "  Copied fly.toml to project root"

    # Launch app (creates on Fly.io, doesn't deploy yet)
    cd "$PROJECT_DIR"
    fly launch --copy-config --no-deploy --yes
    echo ""

    # No persistent volume — vectors live in Chroma Cloud.

    # Prompt for secrets
    cat <<'EOF'
>>> Set your secrets (Auth0 OIDC — recommended for multi-user):

  fly secrets set \
      OPENAI_API_KEY=sk-proj-... \
      CHROMA_HOST=europe-west1.gcp.trychroma.com \
      CHROMA_API_KEY=... \
      CHROMA_TENANT=... \
      CHROMA_DATABASE=... \
      AUTH0_DOMAIN=yourtenant.eu.auth0.com \
      AUTH0_CLIENT_ID=... \
      AUTH0_CLIENT_SECRET=... \
      OAUTH2_PROXY_COOKIE_SECRET="$(openssl rand -base64 32)" \
      PUBLIC_HOSTNAME=amr-learning-agent.fly.dev \
      OAUTH2_ALLOWED_EMAILS=a@x.com,b@y.com

>>> Optional:
  fly secrets set LOGFIRE_API_KEY=...

>>> Single-user fallback (skip Auth0):
  fly secrets set AMR_AUTH_PASSWORD=your-secure-password

>>> Then deploy with: ./scripts/deploy_fly.sh
EOF
    exit 0
fi

# ── Deploy ────────────────────────────────────────────────────────
echo "=== AMR Fly.io Deploy ==="

# Ensure fly.toml is in project root
if [ ! -f "$PROJECT_DIR/fly.toml" ]; then
    cp "$FLY_TOML" "$PROJECT_DIR/fly.toml"
    echo "  Copied fly.toml to project root"
fi

cd "$PROJECT_DIR"

echo ">>> Deploying to Fly.io..."
fly deploy

echo ""
echo "=== Deploy complete ==="
fly status
echo ""
echo "Open in browser: fly open"
