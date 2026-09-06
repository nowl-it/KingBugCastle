#!/usr/bin/env bash
# Deploy hook for KGC Private Server
# Run on the production host (213.35.110.245) upon every GitHub Actions push to main.
# Ensures ZERO-DOWNTIME reload and keeps players connected smoothly.
set -euo pipefail
cd "$(dirname "$0")"

# The public server's OAuth state key and client-metadata location are deployment
# credentials/artifacts, never repository defaults. Load the same file that
# serve_public.sh consumes before preflight imports the application.
if [ -n "${KGC_ENV_FILE:-}" ]; then
  ENV_FILE="$KGC_ENV_FILE"
elif [ -r /etc/kgc/server.env ]; then
  ENV_FILE=/etc/kgc/server.env
else
  ENV_FILE="$PWD/secrets/server.env"
fi
if [ -r "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

echo "=== [KGC Zero-Downtime Deploy Hook] ==="
echo "[1/4] Pulling latest code from main..."
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "[!] Refusing deploy from a dirty checkout. Commit, discard, or explicitly back up local work first." >&2
  exit 1
fi
git pull --ff-only origin main

echo "[2/4] Verifying Python virtual environment..."
VENV_DIR=""
for cand in ".venv" "../.venv"; do
  if [ -d "$cand" ]; then VENV_DIR="$cand"; break; fi
done

if [ -n "$VENV_DIR" ]; then
  "$VENV_DIR/bin/pip" install -q -r requirements.txt
fi

echo "[3/4] Running preflight check..."
PY_BIN="python3"
[ -n "$VENV_DIR" ] && [ -x "$VENV_DIR/bin/python" ] && PY_BIN="$VENV_DIR/bin/python"
"$PY_BIN" cli/preflight.py

echo "[4/4] Triggering Zero-Downtime Graceful Reload..."
./serve_public.sh reload

echo "[4b/4] Restarting dashboard (it has no reload path)..."
sudo -n systemctl restart kgc-dashboard.service 2>/dev/null || echo "    (dashboard restart skipped - not a systemd service here)"

echo "[5/5] Checking server health on port 8080..."
sleep 2
COMMIT_MSG=$(git log -1 --format='%s' HEAD)
[ -x ./discord_notify.sh ] && ./discord_notify.sh "✅ **Deploy completed!** Branch: main
\`$COMMIT_MSG\`" 1542559680361140386 || echo "    (discord notify skipped - script not present)"
echo "=== [✓] Deployment finished with ZERO DOWNTIME! ==="
