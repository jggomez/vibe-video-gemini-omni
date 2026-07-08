#!/bin/bash
# deploy.sh — Manual deployment script for Vibe Video Studio
# Usage: ./deploy.sh [backend|frontend|all]
# Requires: gcloud CLI authenticated, GEMINI_API_KEY set in Secret Manager
set -euo pipefail

PROJECT=video-gemini-omni
REGION=us-central1
SERVICE=vibe-video-studio
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/vibe-video-studio/${SERVICE}"

deploy_backend() {
  echo "▶ Building and pushing Docker image..."
  docker build --platform linux/amd64 -t "${IMAGE}:latest" .
  docker push "${IMAGE}:latest"

  echo "▶ Deploying to Cloud Run..."
  gcloud run deploy "${SERVICE}" \
    --image "${IMAGE}:latest" \
    --region "${REGION}" \
    --platform managed \
    --service-account "vibe-video-sa@${PROJECT}.iam.gserviceaccount.com" \
    --set-env-vars "^;^LOGS_BUCKET_NAME=videos-gemini-omni;GOOGLE_CLOUD_PROJECT=${PROJECT};ALLOW_ORIGINS=https://${PROJECT}.web.app,https://${PROJECT}.firebaseapp.com" \
    --allow-unauthenticated \
    --min-instances 0 \
    --max-instances 10 \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300s \
    --concurrency 80 \
    --port 8080 \
    --project "${PROJECT}"

  echo "✅ Backend deployed!"
  gcloud run services describe "${SERVICE}" --region "${REGION}" --project "${PROJECT}" \
    --format "value(status.url)"
}

deploy_frontend() {
  echo "▶ Deploying Firebase Hosting..."
  npx -y firebase-tools@latest deploy --only hosting --project "${PROJECT}"
  echo "✅ Frontend deployed to https://${PROJECT}.web.app"
}

case "${1:-all}" in
  backend)  deploy_backend ;;
  frontend) deploy_frontend ;;
  all)
    deploy_backend
    deploy_frontend
    ;;
  *)
    echo "Usage: $0 [backend|frontend|all]"
    exit 1
    ;;
esac
