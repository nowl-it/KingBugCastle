#!/usr/bin/env bash
# Manual start/stop for the coupon bot dashboard (the systemd unit above is
# what runs in production; this wrapper exists for local testing and for boxes
# without the unit installed).
#
#   ./serve_coupon.sh [start|restart|stop|status]
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE="${KGC_ENV_FILE:-/etc/kgc/coupon.env}"
if [ -r "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
elif [ -r secrets/coupon.env ]; then
  set -a
  # shellcheck disable=SC1090
  . secrets/coupon.env
  set +a
fi

PORT="${COUPON_WEB_PORT:-8083}"
BIND_HOST="${COUPON_WEB_BIND:-0.0.0.0}"   # public on purpose - password guards it
PID_FILE="/tmp/kgc_coupon.pid"
LOG_FILE="/tmp/kgc_coupon.log"

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
      echo "[+] Coupon dashboard already running (PID $(cat "$PID_FILE"))"
      exit 0
    fi
    nohup "$UVICORN" couponbot.web:app --host "$BIND_HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
    echo "$!" > "$PID_FILE"
    echo "[+] Coupon dashboard: ${BIND_HOST}:${PORT} (PID $!)"
    echo "    Log: $LOG_FILE"
    ;;
  restart)
    stop
    exec "$0" start
    ;;
  stop)
    stop
    echo "[+] Coupon dashboard stopped"
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "[+] Coupon dashboard running (PID $(cat "$PID_FILE"), :${PORT})"
    else
      echo "[!] Coupon dashboard is not running"
      exit 1
    fi
    ;;
  *)
    echo "usage: $0 [start|restart|stop|status]" >&2
    exit 2
    ;;
esac
