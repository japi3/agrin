#!/usr/bin/env bash
#
# Deploy AgriN to Google Cloud Run.
#
# Cloud Run rather than GKE because the workload is bursty and I/O-bound:
# a farmer asks a question, the service waits on SoilGrids, Open-Meteo and
# Gemini, then goes idle. Scale-to-zero means an off-season district costs
# nothing, and a state agriculture department is not running a cluster.
#
# Usage:
#   export GOOGLE_CLOUD_PROJECT=your-project-id
#   export GEMINI_API_KEY=your-key            # or use Vertex AI, see below
#   ./deploy/cloudrun.sh
#
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
# asia-south1 (Mumbai) by default: this is an Indian agricultural service, and
# both latency and data residency argue for keeping it in-country.
REGION="${GOOGLE_CLOUD_LOCATION:-asia-south1}"
SERVICE="${SERVICE_NAME:-agrin}"
REPO="${ARTIFACT_REPO:-agrin}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}"

echo "==> Project ${PROJECT}, region ${REGION}"

echo "==> Enabling required APIs"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  --project "${PROJECT}"

echo "==> Ensuring Artifact Registry repository exists"
gcloud artifacts repositories describe "${REPO}" \
    --location "${REGION}" --project "${PROJECT}" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "${REPO}" \
    --repository-format=docker --location "${REGION}" \
    --description="AgriN container images" --project "${PROJECT}"

echo "==> Building image with Cloud Build"
# Built remotely rather than locally so the deploy works from any machine and
# produces a linux/amd64 image regardless of the developer's architecture --
# an arm64 image built on an Apple laptop will not start on Cloud Run.
gcloud builds submit --tag "${IMAGE}:latest" --project "${PROJECT}" .

# --- Secrets -----------------------------------------------------------
# The Gemini key is passed as a secret rather than a plain env var so it does
# not appear in the service description or in deployment logs.
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  echo "==> Storing Gemini API key in Secret Manager"
  gcloud services enable secretmanager.googleapis.com --project "${PROJECT}"
  if ! gcloud secrets describe agrin-gemini-key --project "${PROJECT}" >/dev/null 2>&1; then
    gcloud secrets create agrin-gemini-key --replication-policy=automatic \
      --project "${PROJECT}"
  fi
  printf '%s' "${GEMINI_API_KEY}" | \
    gcloud secrets versions add agrin-gemini-key --data-file=- --project "${PROJECT}"
  SECRET_FLAG="--set-secrets=GEMINI_API_KEY=agrin-gemini-key:latest"
else
  # No key: fall back to Vertex AI with the service account's own identity,
  # which is the better production posture anyway -- no key to rotate or leak.
  echo "==> No GEMINI_API_KEY set; configuring Vertex AI with ADC"
  SECRET_FLAG="--set-env-vars=GOOGLE_GENAI_USE_VERTEXAI=true"
fi

echo "==> Deploying to Cloud Run"
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}:latest" \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 2 \
  --memory 2Gi \
  --timeout 300 \
  --concurrency 40 \
  --min-instances 0 \
  --max-instances 20 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=${REGION},AGRIN_CORS_ORIGINS=*" \
  ${SECRET_FLAG}

URL=$(gcloud run services describe "${SERVICE}" --region "${REGION}" \
        --project "${PROJECT}" --format='value(status.url)')

echo
echo "==> Deployed: ${URL}"
echo "    Health:   ${URL}/api/health"
echo
echo "Notes:"
echo "  * memory 2Gi: rasterio/GDAL holds Sentinel-2 windows in memory during"
echo "    NDVI reads, and 1Gi is not enough headroom for concurrent requests."
echo "  * timeout 300s: a cold satellite query reads a dozen COGs over HTTP."
echo "  * concurrency 40: the work is I/O-bound, so one instance serves many"
echo "    waiting requests; CPU is idle most of the time."
echo "  * min-instances 0 means the first request after idle is slow. For a"
echo "    launch or a demo, set --min-instances 1."
echo "  * The disk cache is per-instance and ephemeral. Warm it after deploy:"
echo "      python scripts/prewarm_india.py --step 1.0"
echo "    or mount a shared volume at /app/.cache for persistence."
