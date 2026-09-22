#!/usr/bin/env bash
# =============================================================================
# One-shot demo runner.
#
# Seeds the database, ensures the sample clip is present, and runs the device
# simulator on the host against the docker-compose backend.
#
# Prerequisites:
#   - `make up` (postgres, redis, backend, dashboard) is running
#   - Simulator dependencies installed:
#       pip install -r scripts/requirements-simulator.txt
#
# Usage:
#   bash scripts/run_demo.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
SAMPLES_DIR="${PROJECT_ROOT}/data/samples"

TARGET_PLATE="MH12AB1234"
BACKEND_URL="${RAKSHAK_BACKEND_URL:-http://localhost:8000}"

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
else
    COMPOSE=(docker-compose)
fi

echo "=== RAKSHAK Demo ==="
echo ""

echo "[1/3] Seeding database ..."
"${COMPOSE[@]}" -f "${PROJECT_ROOT}/docker-compose.yml" exec -T backend \
    python scripts/seed_db.py
echo ""

echo "[2/3] Checking sample videos ..."
if [ ! -f "${SAMPLES_DIR}/sample1.mp4" ]; then
    bash "${SCRIPT_DIR}/download_sample_videos.sh"
else
    echo "  Sample videos already present."
fi
echo ""

if ! python3 -c "import cv2, easyocr, numpy, requests, ultralytics" 2>/dev/null; then
    echo "ERROR: simulator dependencies are missing." >&2
    echo "Install them with: pip install -r scripts/requirements-simulator.txt" >&2
    exit 1
fi

echo "[3/3] Starting device simulator ..."
echo "  Target plate : ${TARGET_PLATE}"
echo "  Backend      : ${BACKEND_URL}"
echo "  Press Ctrl+C to stop."
echo ""

python3 "${SCRIPT_DIR}/device_simulator.py" \
    --video "${SAMPLES_DIR}/sample1.mp4" \
    --plate "${TARGET_PLATE}" \
    --backend "${BACKEND_URL}" \
    --device-email volunteer@rakshak.local \
    --device-password Vol@12345 \
    --lat 19.0760 \
    --lng 72.8777
