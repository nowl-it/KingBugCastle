#!/usr/bin/env bash
# Dedicated public Player Dashboard. The game API stays on :8080 and the admin
# dashboard on :8081; expose this process through a hostname-specific proxy.
set -euo pipefail
cd "$(dirname "$0")"

# Match the systemd service: deployment secrets and proxy policy belong in an
# operator-owned file, not an interactive shell. The portal is proxied by Caddy,
# so bind loopback by default and make trusting forwarded headers conditional on
# that network invariant.
ENV_FILE="${KGC_ENV_FILE:-/etc/kgc/playerportal.env}"
if [ -r "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

PORTAL_PORT="${PLAYER_PORTAL_PORT:-8082}"
BIND_HOST="${KGC_BIND_HOST:-127.0.0.1}"
PID_FILE="/tmp/kgc_playerportal.pid"
LOG_FILE="/tmp/kgc_playerportal.log"

# This is the browser origin, not an internal bind address. It must match the
# Cloudflare hostname and the Google OAuth redirect URI registered in the console.
export PLAYER_PORTAL_PUBLIC_URL="${PLAYER_PORTAL_PUBLIC_URL:-https://player.kingbugcastle.id.vn}"
# Keep OAuth state valid when this small process restarts. It is a deployment secret,
# so public startup must receive it from the service environment.
: "${GLOGIN_STATE_SECRET:?set GLOGIN_STATE_SECRET in the deployment environment}"
export GLOGIN_STATE_SECRET

if [ "${KGC_TRUST_PROXY:-}" = "1" ] && [ "$BIND_HOST" != "127.0.0.1" ] && [ "$BIND_HOST" != "::1" ]; then
  echo "[!] KGC_TRUST_PROXY=1 requires KGC_BIND_HOST=127.0.0.1 or ::1" >&2
  exit 2
fi
export KGC_BIND_HOST="$BIND_HOST"

UVICORN="uvicorn"
for cand in "../.venv/bin/uvicorn" ".venv/bin/uvicorn"; do
  if [ -x "$cand" ]; then UVICORN="$(cd "$(dirname "$cand")" && pwd)/$(basename "$cand")"; break; fi
done

stop() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")"
  fi
  rm -f "$PID_FILE"
}

case "${1:-start}" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "[+] Player Dashboard already running (PID $(cat "$PID_FILE"))"
      exit 0
    fi
    nohup "$UVICORN" playerportal_server:app --host "$BIND_HOST" --port "$PORTAL_PORT" >"$LOG_FILE" 2>&1 &
    echo "$!" > "$PID_FILE"
    echo "[+] Player Dashboard: ${BIND_HOST}:${PORTAL_PORT} (PID $!)"
    echo "    Browser origin: ${PLAYER_PORTAL_PUBLIC_URL}/"
    echo "    Log: $LOG_FILE"
    ;;
  restart)
    stop
    exec "$0" start
    ;;
  stop)
    stop
    echo "[+] Player Dashboard stopped"
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "[+] Player Dashboard running (PID $(cat "$PID_FILE"), :${PORTAL_PORT})"
    else
      echo "[!] Player Dashboard is not running"
      exit 1
    fi
    ;;
  *)
    echo "usage: $0 [start|restart|stop|status]" >&2
    exit 2
    ;;
esac
