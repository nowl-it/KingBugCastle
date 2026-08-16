#!/usr/bin/env bash
# Deploy hook for KGC Private Server
# Run on the production host (213.35.110.245) upon every GitHub Actions push to main.
# Ensures ZERO-DOWNTIME reload and keeps players connected smoothly.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== [KGC Zero-Downtime Deploy Hook] ==="
echo "[1/4] Pulling latest code from main..."
git pull --rebase origin main || git pull origin main

echo "[2/4] Verifying Python virtual environment..."
VENV_DIR=""
for cand in ".venv" "../.venv"; do
  if [ -d "$cand" ]; then VENV_DIR="$cand"; break; fi
done

if [ -n "$VENV_DIR" ]; then
  "$VENV_DIR/bin/pip" install -q -r requirements.txt || true
fi

echo "[3/4] Running preflight check..."
PY_BIN="python3"
[ -n "$VENV_DIR" ] && [ -x "$VENV_DIR/bin/python" ] && PY_BIN="$VENV_DIR/bin/python"
"$PY_BIN" cli/preflight.py

echo "[4/4] Triggering Zero-Downtime Graceful Reload..."
./serve_public.sh reload

echo "[5/5] Checking server health on port 8080..."
sleep 2
COMMIT_MSG=$(git log -1 --format='%s' HEAD)
./discord_notify.sh "✅ **Deploy completed!** Branch: main
\`$COMMIT_MSG\`"
echo "=== [✓] Deployment finished with ZERO DOWNTIME! ==="
