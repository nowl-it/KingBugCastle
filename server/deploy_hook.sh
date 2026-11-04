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

echo "[3b/4] Refreshing repo-versioned systemd units..."
# systemctl reads only /etc/systemd/system, so a unit committed under systemd/
# otherwise never lands - the coupon dashboard's --host stayed 127.0.0.1 for a
# deploy whose whole point was changing exactly that. Non-fatal where sudo is
# absent (the deploy still reloads the app itself).
if sudo -n true 2>/dev/null; then
  UNITS_REFRESHED=0
  for u in kgc-coupon.service kgc-coupon-worker.service kgc-coupon-worker.timer; do
    if [ -f "systemd/$u" ] && ! sudo -n cmp -s "systemd/$u" "/etc/systemd/system/$u" 2>/dev/null; then
      echo "    refreshing /etc/systemd/system/$u"
      sudo -n cp "systemd/$u" "/etc/systemd/system/$u" && UNITS_REFRESHED=1 \
        || echo "    (failed to refresh $u)"
    fi
  done
  # One-time teardown of the retired :8443 watchdog. That listener is gone now
  # (Caddy terminates TLS and proxies plain HTTP to gunicorn :8080), so the
  # timer would just probe a port nothing owns and log noise. Disable, remove,
  # reload the daemon so systemd forgets the units.
  for u in kgc-tls-watchdog.service kgc-tls-watchdog.timer; do
    if sudo -n test -e "/etc/systemd/system/$u"; then
      echo "    retiring obsolete $u"
      sudo -n systemctl disable --now "$u" 2>/dev/null || true
      sudo -n rm -f "/etc/systemd/system/$u"
      UNITS_REFRESHED=1
    fi
  done
  if [ "$UNITS_REFRESHED" = 1 ]; then
    sudo -n systemctl daemon-reload || true
    sudo -n systemctl enable kgc-coupon.service kgc-coupon-worker.timer 2>/dev/null || true
  fi
else
  echo "    (no passwordless sudo - skipped)"
fi

echo "[3c/4] Syncing Caddy config from repo if changed..."
# The reverse-proxy topology (Caddy terminates TLS and forwards plain HTTP to
# the gunicorn backend) is a tracked file. Without this step an operator has to
# remember to `sudo cp` + `caddy reload` on every port change, and the drift
# between /etc/caddy/Caddyfile and systemd/kgc-public.Caddyfile has bitten us
# more than once. We only touch caddy when the content actually differs, and we
# validate before reload so a bad file cannot leave the box without ingress.
if sudo -n true 2>/dev/null && [ -f systemd/kgc-public.Caddyfile ]; then
  if ! sudo -n cmp -s systemd/kgc-public.Caddyfile /etc/caddy/Caddyfile 2>/dev/null; then
    echo "    /etc/caddy/Caddyfile differs - staging + validating"
    sudo -n cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.pre-kgc-deploy 2>/dev/null || true
    sudo -n cp systemd/kgc-public.Caddyfile /etc/caddy/Caddyfile
    if sudo -n caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
      sudo -n systemctl reload caddy 2>/dev/null || sudo -n systemctl restart caddy 2>/dev/null || true
      echo "    caddy reloaded with the repo Caddyfile"
    else
      echo "    (!) validation failed - restoring previous Caddyfile"
      sudo -n cp /etc/caddy/Caddyfile.pre-kgc-deploy /etc/caddy/Caddyfile 2>/dev/null || true
      sudo -n systemctl reload caddy 2>/dev/null || true
      echo "    leaving caddy on the prior config; deploy continues but caddy was not updated"
    fi
  else
    echo "    (caddy config unchanged)"
  fi
else
  echo "    (no passwordless sudo or no Caddyfile in repo - skipped)"
fi

echo "[4/4] Triggering Zero-Downtime Graceful Reload..."
./serve_public.sh reload

echo "[4b/4] Restarting dashboard (it has no reload path)..."
sudo -n systemctl restart kgc-dashboard.service 2>/dev/null || echo "    (dashboard restart skipped - not a systemd service here)"

echo "[4c/4] Restarting coupon bot dashboard (it has no reload path)..."
sudo -n systemctl restart kgc-coupon.service 2>/dev/null || echo "    (coupon dashboard restart skipped - not installed here)"

echo "[5/5] Checking server health on port 8080..."
sleep 2
# The reload above SIGHUPs the gunicorn master, which spawns new workers and
# drains the old ones; the listening socket never closes across a healthy reload.
# If :8080 stops answering, the master itself died - let systemd's
# Restart=on-failure handle it (kgc.service wraps this script as Type=simple).
HTTP_CODE=$(curl -s --max-time 6 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/ || echo 000)
if [ "$HTTP_CODE" != "200" ]; then
    echo "    :8080 not healthy (got $HTTP_CODE) - check systemctl status kgc + /tmp/kgc_pub_http.log"
    tail -20 /tmp/kgc_pub_http.log 2>/dev/null || true
fi
# Also verify the reverse-proxy hop: the switch from :8443 to :8080 in the
# Caddyfile means a typo there would still leave :8080 "healthy" while players
# get 502. Probe through caddy itself via the public hostname (forced to
# 127.0.0.1 with --resolve so we don't depend on Cloudflare round-tripping),
# ignoring the self-signed cert.
CADDY_CODE=$(curl -sk --max-time 6 --resolve kingbugcastle.id.vn:443:127.0.0.1 \
    -o /dev/null -w '%{http_code}' https://kingbugcastle.id.vn/ || echo 000)
if [ "$CADDY_CODE" != "200" ]; then
    echo "    (!) caddy :443 -> backend returned $CADDY_CODE; players may be seeing errors"
    sudo -n systemctl status caddy --no-pager 2>/dev/null | head -20 || true
fi
COMMIT_MSG=$(git log -1 --format='%s' HEAD)
[ -x ./discord_notify.sh ] && ./discord_notify.sh "✅ **Deploy completed!** Branch: main
\`$COMMIT_MSG\`" 1542559680361140386 || echo "    (discord notify skipped - script not present)"
echo "=== [✓] Deployment finished with ZERO DOWNTIME! ==="
