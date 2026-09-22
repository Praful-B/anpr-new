#!/usr/bin/env bash
# =============================================================================
# RAKSHAK — Full Demo Launcher
#
# Single script that brings up the entire stack, seeds demo data, downloads
# sample videos, installs host-side simulator dependencies, and runs the
# device simulator so you can see the dashboard light up with live hits.
#
# Usage:
#   bash start_demo.sh              # full demo (all steps)
#   bash start_demo.sh --no-sim     # start infra only, skip simulator
#   bash start_demo.sh --teardown   # tear down everything
#
# Prerequisites:
#   - Docker & Docker Compose
#   - Python 3.11+ (for the host-side device simulator)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BACKEND_URL="${RAKSHAK_BACKEND_URL:-http://localhost:8000}"
DASHBOARD_URL="http://localhost:5173"
HEALTH_RETRIES=30
TARGET_PLATE="MH12AB1234"
SAMPLES_DIR="${SCRIPT_DIR}/data/samples"

# Demo credentials
ADMIN_EMAIL="admin@rakshak.local"
ADMIN_PASS="Admin@123"
COP_EMAIL="cop@rakshak.local"
COP_PASS="Cop@12345"
CITIZEN_EMAIL="citizen@rakshak.local"
CITIZEN_PASS="Cit@12345"
VOLUNTEER_EMAIL="volunteer@rakshak.local"
VOLUNTEER_PASS="Vol@12345"

# ---------------------------------------------------------------------------
# Detect docker compose command
# ---------------------------------------------------------------------------
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

# ---------------------------------------------------------------------------
# Colours / helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*"; }
step()    { echo -e "\n${BOLD}━━━ Step $1/5: $2 ━━━${NC}"; }

# ---------------------------------------------------------------------------
# Teardown mode
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--teardown" ]]; then
    info "Tearing down the RAKSHAK stack ..."
    $COMPOSE down -v
    ok "Stack removed."
    exit 0
fi

SKIP_SIM=false
if [[ "${1:-}" == "--no-sim" ]]; then
    SKIP_SIM=true
fi

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo -e "${BOLD}"
cat << 'EOF'
=================================================================
  Automatic Number Plate Recognition — Stolen Vehicle Detection
  Privacy-first ANPR network for Indian licence plates
=================================================================
EOF
echo -e "${NC}"

# =============================================================================
# Step 1: Ensure .env exists
# =============================================================================
step 1 "Environment setup"

if [ ! -f .env ]; then
    info "No .env found — copying from .env.example ..."
    cp .env.example .env
    ok ".env created."
else
    ok ".env already present."
fi

# =============================================================================
# Step 2: Build and start the Docker stack
# =============================================================================
step 2 "Building & starting Docker stack (postgres, redis, backend, dashboard)"

# Create upload directory if it doesn't exist
mkdir -p data/uploads

info "Building images and starting services ..."
$COMPOSE up --build -d

echo ""
info "Waiting for services to become healthy ..."

# Wait for backend
echo -n "  Backend  "
for i in $(seq 1 $HEALTH_RETRIES); do
    if curl -fsS "${BACKEND_URL}/healthz" >/dev/null 2>&1; then
        echo -e "${GREEN}ready${NC}"
        break
    fi
    if [ "$i" -eq "$HEALTH_RETRIES" ]; then
        echo -e "${RED}timeout${NC}"
        err "Backend did not become healthy in time."
        err "Check logs: $COMPOSE logs backend"
        exit 1
    fi
    echo -n "."
    sleep 2
done

# Wait for dashboard
echo -n "  Dashboard"
for i in $(seq 1 $HEALTH_RETRIES); do
    if curl -fsS "${DASHBOARD_URL}" >/dev/null 2>&1; then
        echo -e "${GREEN}ready${NC}"
        break
    fi
    if [ "$i" -eq "$HEALTH_RETRIES" ]; then
        echo -e "${RED}timeout${NC}"
        err "Dashboard did not become healthy in time."
        err "Check logs: $COMPOSE logs dashboard"
        exit 1
    fi
    echo -n "."
    sleep 2
done

# Wait for Redis
echo -n "  Redis    "
for i in $(seq 1 10); do
    if $COMPOSE exec -T redis redis-cli ping >/dev/null 2>&1; then
        echo -e "${GREEN}ready${NC}"
        break
    fi
    echo -n "."
    sleep 1
done

# Wait for Postgres
echo -n "  Postgres "
for i in $(seq 1 10); do
    if $COMPOSE exec -T postgres pg_isready -U postgres >/dev/null 2>&1; then
        echo -e "${GREEN}ready${NC}"
        break
    fi
    echo -n "."
    sleep 1
done

ok "All services are up."

# =============================================================================
# Step 3: Seed demo data
# =============================================================================
step 3 "Seeding demo data (users + hotlist)"

info "Running seed script inside backend container ..."
$COMPOSE exec -T backend python scripts/seed_db.py
ok "Database seeded with 4 demo users and plate ${TARGET_PLATE}."

# =============================================================================
# Step 4: Download sample videos + install simulator deps
# =============================================================================
step 4 "Preparing device simulator"

# Download sample videos
if [ ! -f "${SAMPLES_DIR}/sample1.mp4" ]; then
    info "Downloading sample videos for the simulator ..."
    bash scripts/download_sample_videos.sh
else
    ok "Sample videos already present."
fi

# Install host-side simulator dependencies if needed
if ! python3 -c "import cv2, easyocr, numpy, requests, ultralytics" 2>/dev/null; then
    info "Installing host-side simulator dependencies (first run only) ..."
    python3 -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r scripts/requirements-simulator.txt
    ok "Simulator dependencies installed."
else
    ok "Simulator dependencies already satisfied."
fi

# =============================================================================
# Step 5: Run the device simulator (unless --no-sim)
# =============================================================================
if [ "$SKIP_SIM" = true ]; then
    echo ""
    echo -e "${BOLD}━━━ Done! ━━━${NC}"
else
    step 5 "Running device simulator"
    echo ""
    info "Target plate  : ${TARGET_PLATE}"
    info "Backend       : ${BACKEND_URL}"
    info "Device email  : ${VOLUNTEER_EMAIL}"
    info "Coordinates   : 19.0760, 72.8777 (Mumbai)"
    echo ""
    info "The simulator will read video frames, detect licence plates,"
    info "and send hit events to the backend. Watch the dashboard!"
    echo ""
    warn "Press Ctrl+C to stop the simulator (the stack keeps running)."
    echo ""

    python3 scripts/device_simulator.py \
        --video "${SAMPLES_DIR}/sample1.mp4" \
        --plate "${TARGET_PLATE}" \
        --backend "${BACKEND_URL}" \
        --device-email "${VOLUNTEER_EMAIL}" \
        --device-password "${VOLUNTEER_PASS}" \
        --lat 19.0760 \
        --lng 72.8777 || true
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  RAKSHAK Demo is running!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${CYAN}Dashboard${NC}      ${DASHBOARD_URL}"
echo -e "  ${CYAN}Backend API${NC}    ${BACKEND_URL}/docs"
echo -e "  ${CYAN}Health check${NC}   ${BACKEND_URL}/healthz"
echo ""
echo -e "  ${BOLD}Demo credentials:${NC}"
echo -e "  ┌──────────────┬────────────────────────┬──────────────┐"
echo -e "  │ Role         │ Email                  │ Password     │"
echo -e "  ├──────────────┼────────────────────────┼──────────────┤"
echo -e "  │ Admin        │ ${ADMIN_EMAIL}    │ ${ADMIN_PASS}     │"
echo -e "  │ Police (COP) │ ${COP_EMAIL}      │ ${COP_PASS}      │"
echo -e "  │ Citizen      │ ${CITIZEN_EMAIL}    │ ${CITIZEN_PASS}      │"
echo -e "  │ Volunteer    │ ${VOLUNTEER_EMAIL}    │ ${VOLUNTEER_PASS}      │"
echo -e "  └──────────────┴────────────────────────┴──────────────┘"
echo ""
echo -e "  ${BOLD}Hotlist plate:${NC} ${TARGET_PLATE}"
echo ""
echo -e "  ${BOLD}Useful commands:${NC}"
echo -e "    $COMPOSE logs -f          Follow all service logs"
echo -e "    $COMPOSE logs backend     Follow backend logs only"
echo -e "    bash start_demo.sh --teardown   Stop and remove everything"
echo -e "    bash start_demo.sh --no-sim     Restart infra without simulator"
echo ""
