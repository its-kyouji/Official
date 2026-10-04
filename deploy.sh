#!/bin/bash
# ==== DEPLOY.SH ====
# Interactive deployment wrapper for Cloud Shell.
# Pulls the officialhq/kyouji:latest image and deploys it to Cloud Run.

set -e

BOLD='\033[1m'
GREEN='\033[1;32m'
CYAN='\033[1;36m'
YELLOW='\033[1;33m'
RESET='\033[0m'

echo -e "${BOLD}${CYAN}=== OFFICIAL RELAY DEPLOYER ===${RESET}"
echo -e "${YELLOW}Architecture by Kyouji${RESET}\n"

# 1. GCP Project Check
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}No active GCP project. Please run 'gcloud init' first.${RESET}"
    exit 1
fi

# 2. Collect Environment Variables
read -p "Service Name [kyouji-relay]: " SERVICE_NAME
SERVICE_NAME=${SERVICE_NAME:-kyouji-relay}

read -p "Region [asia-southeast1]: " REGION
REGION=${REGION:-asia-southeast1}

read -p "System UUID (Blank to auto-generate): " SYS_UUID
read -p "Core Password [official-secret]: " PASSWORD
PASSWORD=${PASSWORD:-official-secret}

read -p "Base Path (e.g., /relay) [/relay]: " BASE_PATH
BASE_PATH=${BASE_PATH:-/relay}

read -p "Ads Mode (normal/off) [normal]: " ADS_MODE
ADS_MODE=${ADS_MODE:-normal}

read -p "Active Cores (xray,singbox) [xray]: " CORES
CORES=${CORES:-xray}

read -p "SSH Stack (dropbear/openssh/off) [dropbear]: " SSH_STACK
SSH_STACK=${SSH_STACK:-dropbear}

# 3. Build Env String
ENV_VARS="PASSWORD=${PASSWORD},BASE_PATH=${BASE_PATH},ADS_MODE=${ADS_MODE},CORES=${CORES},SSH_STACK=${SSH_STACK}"
if [ -n "$SYS_UUID" ]; then
    ENV_VARS="${ENV_VARS},UUID=${SYS_UUID}"
fi

# 4. Deploy to Cloud Run
echo -e "\n${CYAN}Deploying to Cloud Run ($REGION)...${RESET}"
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
    --memory 2Gi \
    --cpu 1 \
    --execution-environment gen2 \
    --no-cpu-throttling \
    --set-env-vars "$ENV_VARS" \
    --project "$PROJECT_ID"

echo -e "\n${GREEN}${BOLD}Deployment Complete!${RESET}"
echo -e "Access your dashboard at the provided Cloud Run URL."
