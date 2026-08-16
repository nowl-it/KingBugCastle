#!/usr/bin/env bash
# Run the KGC private server for REMOTE players (the shared XAPK points here).
#
# The client hits https://<baked-host>/  on port 443. Pick ONE exposure path:
#
#   A. Cloudflare Tunnel (recommended - no static IP, no open ports, valid TLS):
#        cloudflared tunnel --url http://localhost:8080          # quick (random host)
#        # or a NAMED tunnel bound to your own short domain (<=26 chars), e.g. kgc.mydomain.com
#      Then rebuild the XAPK with that host:  --host kgc.mydomain.com
#      Only the :8080 HTTP server below is needed (Cloudflare terminates TLS).
#
#   B. Static public IP + port-forward 443 -> this box:
#      Forward external 443 to local 8443 (this script's TLS port), bake --host <your.ip>.
#
#   C. LAN test: bake --host <this-box-LAN-ip>, players on same Wi-Fi hit :443 (forward 443->8443).
#
# The SSL-bypass patch makes the client accept ANY cert, so the self-signed cert.pem is fine.
set -euo pipefail
cd "$(dirname "$0")"

HTTP_PORT="${HTTP_PORT:-8080}"
TLS_PORT="${TLS_PORT:-8443}"
PID_FILE="/tmp/kgc_server.pid"

# Inject real Google OAuth client for public testing. Google requires a HTTPS domain.
export GLOGIN_PUBLIC_URL="https://kingbugcastle.id.vn"
# Fixed state secret so OAuth state tokens survive server restarts.
export GLOGIN_STATE_SECRET="${GLOGIN_STATE_SECRET:-a3f7c91e8b2d4f6a0e5c8b3d7f9a2e4c}"

# Prefer the repo venv, same as run.sh.
UVICORN="uvicorn"
GUNICORN="gunicorn"
for cand in "../.venv/bin/uvicorn" ".venv/bin/uvicorn"; do
  if [ -x "$cand" ]; then UVICORN="$(cd "$(dirname "$cand")" && pwd)/$(basename "$cand")"; break; fi
done
for cand in "../.venv/bin/gunicorn" ".venv/bin/gunicorn"; do
  if [ -x "$cand" ]; then GUNICORN="$(cd "$(dirname "$cand")" && pwd)/$(basename "$cand")"; break; fi
done

PY_BIN="${UVICORN%/uvicorn}/python"
[ -x "$PY_BIN" ] || PY_BIN="python3"

IS_BG=0

# Subcommands: reload | start | stop | status
case "${1:-}" in
  reload)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      PID=$(cat "$PID_FILE")
      echo "[+] Sending SIGHUP to master process (PID: $PID) for Zero-Downtime reload..."
      kill -HUP "$PID"

      # Also restart TLS uvicorn (separate process, not managed by gunicorn SIGHUP)
      TLS_PID=$(pgrep -f "uvicorn.*server:app.*--port.*${TLS_PORT}" 2>/dev/null | head -1 || true)
      if [ -n "$TLS_PID" ]; then
        echo "[+] Restarting TLS uvicorn (PID: $TLS_PID)..."
        kill "$TLS_PID" 2>/dev/null || true
        sleep 1
        if [ -f key.pem ] && [ -f cert.pem ]; then
          nohup "$UVICORN" server:app --host 0.0.0.0 --port "${TLS_PORT}" \
              --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/kgc_pub_tls.log 2>&1 &
          echo "[✓] TLS uvicorn restarted (PID: $!)"
        fi
      fi

      sleep 2
      if kill -0 "$PID" 2>/dev/null; then
        echo "[✓] Zero-downtime reload complete! New workers spawned, active requests preserved."
        DISCORD_DIR="$(dirname "$0")"
        [ -x "$DISCORD_DIR/discord_notify.sh" ] && "$DISCORD_DIR/discord_notify.sh" "🔄 **Server reloaded!** Zero-downtime, no player disconnects." &
        exit 0
      fi
    fi
    echo "[!] Master process not running or PID file missing. Starting server in background..."
    IS_BG=1
    ;;
  start|daemon)
    IS_BG=1
    ;;
  stop)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      PID=$(cat "$PID_FILE")
      echo "[+] Stopping master process (PID: $PID)..."
      kill "$PID" || true
      rm -f "$PID_FILE"
    fi
    pkill -f "gunicorn.*server:app" 2>/dev/null || true
    pkill -f "uvicorn.*server:app" 2>/dev/null || true
    echo "[✓] Server stopped."
    exit 0
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "[✓] Master process is running with PID $(cat "$PID_FILE")."
      ps -ef | grep -E "gunicorn|uvicorn" | grep -v grep || true
    else
      echo "[!] Server is not running."
    fi
    exit 0
    ;;
esac

# Registration is open by definition here: the client picks its own account id. Keep
# the caps explicit rather than relying on defaults nobody remembers.
export KGC_MAX_PLAYERS="${KGC_MAX_PLAYERS:-200}"
export KGC_NEW_PLAYER_PER_IP="${KGC_NEW_PLAYER_PER_IP:-5}"
export KGC_RATE_LIMIT="${KGC_RATE_LIMIT:-600}"
export KGC_RATE_BAN_AFTER="${KGC_RATE_BAN_AFTER:-5}"
export KGC_RATE_BAN_SECONDS="${KGC_RATE_BAN_SECONDS:-900}"
export KGC_IPTABLES_BAN="${KGC_IPTABLES_BAN:-0}"
export KGC_MAX_BODY="${KGC_MAX_BODY:-1000000}"
export KGC_QUIET="${KGC_QUIET:-1}"
[ -n "${KGC_ADMIN_TOKEN:-}" ] && export KGC_ADMIN_TOKEN
[ -n "${KGC_TRUST_PROXY:-}" ] && export KGC_TRUST_PROXY

# Run preflight checks before serving
echo "[+] preflight"
if ! "$PY_BIN" cli/preflight.py; then
  echo ""
  echo "[!] refusing to serve publicly. Fix the FAIL lines above, then re-run."
  exit 1
fi
echo ""

# Prefer Gunicorn with Uvicorn workers for zero-downtime SIGHUP reload & concurrency
if command -v "$GUNICORN" >/dev/null 2>&1 || [ -x "$GUNICORN" ]; then
  echo "[+] Starting Gunicorn + Uvicorn Workers on 0.0.0.0:${HTTP_PORT} (Zero-Downtime Ready)..."
  nohup "$GUNICORN" server:app -c gunicorn_conf.py > /tmp/kgc_pub_http.log 2>&1 &
  P1=$!
  echo "$P1" > "$PID_FILE"
else
  echo "[!] gunicorn not found; falling back to standalone uvicorn..."
  nohup "$UVICORN" server:app --host 0.0.0.0 --port "${HTTP_PORT}" > /tmp/kgc_pub_http.log 2>&1 &
  P1=$!
  echo "$P1" > "$PID_FILE"
fi

if [ -f key.pem ] && [ -f cert.pem ]; then
  echo "[+] HTTPS TLS server 0.0.0.0:${TLS_PORT}"
  nohup "$UVICORN" server:app --host 0.0.0.0 --port "${TLS_PORT}" \
      --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/kgc_pub_tls.log 2>&1 &
  P2=$!
else
  echo "[!] cert.pem/key.pem missing - HTTPS not started (Cloudflare Tunnel terminates TLS)"
  P2=""
fi

echo ""
echo "  HTTP  :${HTTP_PORT}  PID ${P1}   (Zero-downtime reload: ./serve_public.sh reload)"
[ -n "${P2}" ] && echo "  HTTPS :${TLS_PORT}  PID ${P2}"
echo ""
echo "  Dashboard (admin + tracker):  $PY_BIN dashboard.py   -> http://localhost:8081"
echo "  Stop:  ./serve_public.sh stop"
echo ""

if [ "$IS_BG" = "1" ]; then
  sleep 2
  echo "[✓] Server process running in background (PID: $P1)."
  DISCORD_DIR="$(dirname "$0")"
  [ -x "$DISCORD_DIR/discord_notify.sh" ] && "$DISCORD_DIR/discord_notify.sh" "🔄 **Server started/restarted!** PID: $P1" &
  exit 0
fi

wait
