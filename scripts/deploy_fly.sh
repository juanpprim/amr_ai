#!/usr/bin/env bash
# Deploy AMR Learning Agent to Fly.io with nginx auth proxy.
#
# Prerequisites:
#   1. Install flyctl: curl -L https://fly.io/install.sh | sh
#   2. Authenticate: fly auth login
#
# First-time setup (run once):
#   ./scripts/deploy_fly.sh --init
#
# Subsequent deploys:
#   ./scripts/deploy_fly.sh
#
# Set auth password:
#   fly secrets set AMR_AUTH_PASSWORD=your-secure-password
#   fly secrets set AMR_AUTH_USER=admin       # optional, default: admin

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

    # Create persistent volume for ChromaDB
    echo ">>> Creating persistent volume (1GB, Madrid)..."
    fly volumes create amr_data --size 1 --region mad --yes || true
    echo ""

    # Prompt for secrets
    echo ">>> Set your secrets:"
    echo "  fly secrets set OPENAI_API_KEY=sk-..."
    echo "  fly secrets set LOGFIRE_API_KEY=..."
    echo "  fly secrets set AMR_AUTH_PASSWORD=your-secure-password"
    echo ""
    echo ">>> Then deploy with: ./scripts/deploy_fly.sh"
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
