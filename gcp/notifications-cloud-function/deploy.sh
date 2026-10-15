#!/usr/bin/env bash
# Deploy the notifications Cloud Function to GCP.
#
# Required environment variables (export before running):
#   RESEND_API_KEY      Resend API key, e.g. re_xxxxxxxxxxxx
#   SENDER_EMAIL        (optional) Verified sender. Defaults to Resend's
#                       shared onboarding domain so it works without
#                       custom-domain verification.
#   GCP_PROJECT_ID      (optional) Override the gcloud-active project.
#   GCP_REGION          (optional) Defaults to us-east1.

set -euo pipefail

FN_NAME="${FN_NAME:-a2-group92-notifications}"
RUNTIME="${RUNTIME:-python312}"
REGION="${GCP_REGION:-us-east1}"
ENTRY_POINT="notifications"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${RESEND_API_KEY:?Set RESEND_API_KEY before running (export RESEND_API_KEY=re_...)}"
SENDER_EMAIL="${SENDER_EMAIL:-Aussie EcoLens <onboarding@resend.dev>}"

if [[ -n "${GCP_PROJECT_ID:-}" ]]; then
    PROJECT_FLAG="--project=$GCP_PROJECT_ID"
else
    PROJECT_FLAG=""
fi

echo "Deploying $FN_NAME to $REGION ..."

gcloud functions deploy "$FN_NAME" \
    --gen2 \
    --runtime="$RUNTIME" \
    --region="$REGION" \
    --source="$SOURCE_DIR" \
    --entry-point="$ENTRY_POINT" \
    --trigger-http \
    --allow-unauthenticated \
    --memory=256MB \
    --timeout=30s \
    --set-env-vars="RESEND_API_KEY=$RESEND_API_KEY,SENDER_EMAIL=$SENDER_EMAIL" \
    $PROJECT_FLAG

echo ""
echo "Deployed. Trigger URL:"
gcloud functions describe "$FN_NAME" \
    --gen2 \
    --region="$REGION" \
    $PROJECT_FLAG \
    --format='value(serviceConfig.uri)'
