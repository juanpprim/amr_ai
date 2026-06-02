#!/usr/bin/env bash
# Deploy AMR Learning Agent to Google Cloud Run.
#
# Prerequisites:
#   1. Install gcloud CLI: https://cloud.google.com/sdk/docs/install
#   2. Authenticate: gcloud auth login
#   3. Create a project: gcloud projects create amr-learning --name="AMR Learning"
#   4. Enable APIs: gcloud services enable run.googleapis.com artifactregistry.googleapis.com
#   5. Create Artifact Registry repo (one-time):
#      gcloud artifacts repositories create amr-docker \
#        --repository-format=docker --location=europe-west1
#
# Usage:
#   ./scripts/deploy_cloudrun.sh                    # deploy with defaults
#   ./scripts/deploy_cloudrun.sh --project my-proj  # custom project
#
# After first deploy, set secrets:
#   gcloud run services update amr-learning-agent \
#     --update-secrets=OPENAI_API_KEY=openai-api-key:latest,LOGFIRE_API_KEY=logfire-key:latest \
#     --region=europe-west1
#
# Restrict access (IAM auth — only specific Google accounts):
#   gcloud run services add-iam-policy-binding amr-learning-agent \
#     --member="user:you@gmail.com" \
#     --role="roles/run.invoker" \
#     --region=europe-west1

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-europe-west1}"
SERVICE="amr-learning-agent"
REPO="amr-docker"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}"
TAG="${1:-$(git rev-parse --short HEAD 2>/dev/null || echo 'latest')}"

if [ -z "$PROJECT" ]; then
    echo "ERROR: No GCP project set. Run: gcloud config set project <PROJECT_ID>"
    exit 1
fi

echo "=== AMR Cloud Run Deploy ==="
echo "  Project:  $PROJECT"
echo "  Region:   $REGION"
echo "  Image:    $IMAGE:$TAG"
echo ""

# ── Build & push ──────────────────────────────────────────────────
echo ">>> Building and pushing Docker image..."
gcloud builds submit \
    --tag "${IMAGE}:${TAG}" \
    --timeout=1200s \
    --quiet

# ── Deploy ────────────────────────────────────────────────────────
echo ">>> Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
    --image "${IMAGE}:${TAG}" \
    --region "$REGION" \
    --port 7860 \
    --memory 2Gi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 2 \
    --timeout 600 \
    --no-allow-unauthenticated \
    --set-env-vars="STREAMLIT_SERVER_PORT=7860" \
    --quiet

# ── Output ────────────────────────────────────────────────────────
URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --format="value(status.url)")
echo ""
echo "=== Deploy complete ==="
echo "  URL: $URL"
echo ""
echo "NOTE: Access is restricted (--no-allow-unauthenticated)."
echo "  Grant access:  gcloud run services add-iam-policy-binding $SERVICE \\"
echo "                   --member='user:EMAIL' --role='roles/run.invoker' --region=$REGION"
echo ""
echo "  Open in browser (authenticated): gcloud run services proxy $SERVICE --region=$REGION"
