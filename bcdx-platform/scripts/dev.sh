#!/usr/bin/env bash
# ============================================================
#  BC-Dx Platform - one-shot development launcher (Unix)
#  Usage: ./scripts/dev.sh
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKEND_PID=""

cleanup() {
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo ""
    echo "Stopping backend (pid $BACKEND_PID)..."
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# ---- 1. model registry -----------------------------------------------------
echo "[1/3] Checking model registry..."
if [[ ! -f "ml/registry/registry.json" ]]; then
  echo "      registry.json missing - training now (this may take a minute)..."
  (cd ml && python pipelines/train.py)
fi

# ---- 2. backend ------------------------------------------------------------
echo "[2/3] Starting backend on http://127.0.0.1:8000 ..."
(cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!

# Wait for the health endpoint before starting the frontend.
for _ in $(seq 1 40); do
  if curl -s --noproxy '*' -o /dev/null "http://127.0.0.1:8000/health" 2>/dev/null; then
    echo "      backend is up"
    break
  fi
  sleep 0.5
done

# ---- 3. frontend -----------------------------------------------------------
echo "[3/3] Starting frontend on http://127.0.0.1:5173 ..."
echo ""
echo "  Backend  : http://127.0.0.1:8000/docs"
echo "  Frontend : http://127.0.0.1:5173"
echo ""
echo "Press Ctrl+C to stop both."
echo ""

cd frontend && npm run dev
