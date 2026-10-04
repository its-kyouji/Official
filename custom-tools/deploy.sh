#!/bin/bash
# Cloud Shell / Local gcloud deploy helper
set -e
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-kyouji-relay}"
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)

echo "Deploying $SERVICE_NAME to Cloud Run ($REGION)..."
gcloud run deploy "$SERVICE_NAME" \
    --image "officialhq/kyouji:latest" \
    --platform managed \
    --region "$REGION" \
    --allow-unauthenticated \
    --port 8080 \
    --min-instances 1 \
    --max-instances 4 \
    --concurrency 1000 \
    --timeout 3600 \
    --memory 4Gi \
    --cpu 2 \
    --execution-environment gen2 \
    --no-cpu-throttling \
    --project "$PROJECT_ID"
