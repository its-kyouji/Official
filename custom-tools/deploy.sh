#!/bin/bash
SERVICE_NAME="kyouji-cli"
REGION="us-central1"
PROJECT_ID=$(gcloud config get-value project)

gcloud run deploy $SERVICE_NAME \
  --source . \
  --region $REGION \
  --allow-unauthenticated \
  --port 8080 \
  --execution-environment gen2 \
  --cpu 1 --memory 512Mi \
  --set-env-vars="PROTO=vless,XPORT=443"
