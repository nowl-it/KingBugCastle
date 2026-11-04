#!/usr/bin/env bash
# Run the KGC private server for REMOTE players (the shared XAPK points here).
#
# The KGC private server listens on ONE HTTP port. How it is exposed to players:
#
#   A. Behind a TLS-terminating reverse proxy (production: Caddy + Cloudflare).
#      Set KGC_TRUST_PROXY=1 + KGC_BIND_HOST=127.0.0.1 in /etc/kgc/server.env; the
#      proxy owns 443 and forwards plain HTTP to this script's :8080. No local TLS
#      listener is started (see TLS_LISTENER below), so the whole box serves one
#      gunicorn pool and reload cannot orphan a second listener.
#
#   B. Cloudflare Tunnel (no static IP, no open ports, valid TLS):
#        cloudflared tunnel --url http://localhost:8080          # quick (random host)
#      Only the :8080 HTTP server below is needed (Cloudflare terminates TLS).
#
#   C. Static public IP / LAN without a proxy - device talks HTTPS directly.
#      This is what local redroid testing does: `adb reverse tcp:443 tcp:8443`
#      expects a TLS uvicorn here. In that mode leave KGC_TRUST_PROXY unset and
#      drop key.pem + cert.pem into server/ so the :8443 listener starts.
#
# The SSL-bypass patch makes the client accept ANY cert, so the self-signed cert.pem is fine.
set -euo pipefail
cd "$(dirname "$0")"

# Keep deployment-only values out of git and make interactive starts behave like
# the deploy hook. The file is operator-owned; do not use a world-writable path.
if [ -n "${KGC_ENV_FILE:-}" ]; then
  ENV_FILE="$KGC_ENV_FILE"
elif [ -r /etc/kgc/server.env ]; then
  ENV_FILE=/etc/kgc/server.env
else
  # A personal-machine deployment normally has no system-owned /etc/kgc.
  # Keep its credentials beside the already gitignored OAuth client instead.
  ENV_FILE="$PWD/secrets/server.env"
fi
if [ -r "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

HTTP_PORT="${HTTP_PORT:-8080}"
TLS_PORT="${TLS_PORT:-8443}"
BIND_HOST="${KGC_BIND_HOST:-0.0.0.0}"
PID_FILE="/tmp/kgc_server.pid"

# TLS listener policy. When a reverse proxy in front of us already terminates TLS
# (KGC_TRUST_PROXY=1), starting a second :8443 uvicorn would double-encrypt every
# request, waste CPU, and - critically - live as a nohup orphan outside
# kgc.service's cgroup so `Restart=on-failure` cannot rescue it after an OOM kill.
# In that mode we serve plain HTTP on :8080 only and let Caddy own TLS. For local
# redroid testing without a proxy, keep spawning :8443 as before so
# `adb reverse tcp:443 tcp:8443` still resolves.
if [ "${KGC_TRUST_PROXY:-}" = "1" ]; then
  TLS_LISTENER=0
else
  TLS_LISTENER=auto
fi

# Browser origin for the game OAuth callback. Preserve the operator-provided
# deployment domain from server.env; the historic public domain is only a default.
export GLOGIN_PUBLIC_URL="${GLOGIN_PUBLIC_URL:-https://kingbugcastle.id.vn}"
# OAuth state must survive a restart, but the key is deployment-only credential
# material. Put it in the service environment; never fall back to a tracked value.
: "${GLOGIN_STATE_SECRET:?set GLOGIN_STATE_SECRET in the deployment environment}"
export GLOGIN_STATE_SECRET

# Prefer the repo venv, same as run.py.
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

      # When we still own a TLS listener (local dev without proxy), cycle it too.
      # The gunicorn SIGHUP does not touch that standalone process, and the port is
      # not released by a HUP alone. Kill by resolved PID, wait for the socket to
      # actually go away (the kernel can hold it a few seconds after SIGKILL), then
      # respawn; the previous inline path raced Errno 98 whenever reload fired
      # twice in a row and left :8443 dark for a whole timer interval.
      if [ "$TLS_LISTENER" != "0" ] && [ -f key.pem ] && [ -f cert.pem ]; then
        _tls_pids=$(pgrep -f "uvicorn server:app .*--port ${TLS_PORT}( |$)" 2>/dev/null || true)
        if [ -n "$_tls_pids" ]; then
          echo "[+] Restarting TLS uvicorn (PIDs: $(echo $_tls_pids | tr '\n' ' '))..."
          kill $_tls_pids 2>/dev/null || true
          for _i in 1 2 3 4 5 6 7 8 9 10; do
            sleep 1
            pgrep -f "uvicorn server:app .*--port ${TLS_PORT}( |$)" >/dev/null 2>&1 || break
          done
          _tls_left=$(pgrep -f "uvicorn server:app .*--port ${TLS_PORT}( |$)" 2>/dev/null || true)
          if [ -n "$_tls_left" ]; then
            echo "[!] TLS uvicorn ignored SIGTERM; SIGKILL $_tls_left"
            kill -9 $_tls_left 2>/dev/null || true
          fi
        fi
        for _i in 1 2 3 4 5; do
          ss -ltn 2>/dev/null | grep -q ":${TLS_PORT} " || break
          sleep 1
        done
        nohup "$UVICORN" server:app --host "$BIND_HOST" --port "${TLS_PORT}" \
            --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/kgc_pub_tls.log 2>&1 &
        _tls_new=$!
        _tls_ok=0
        for _i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
          sleep 1
          if curl -m 3 -sk -o /dev/null "https://127.0.0.1:${TLS_PORT}/" 2>/dev/null; then
            _tls_ok=1; break
          fi
        done
        if [ "$_tls_ok" = 1 ]; then
          echo "[✓] TLS uvicorn restarted (PID: $_tls_new), verified on :${TLS_PORT}"
        else
          echo "[X] TLS uvicorn NOT answering on :${TLS_PORT} - check /tmp/kgc_pub_tls.log"
          tail -5 /tmp/kgc_pub_tls.log || true
        fi
      else
        echo "[i] TLS listener managed by reverse proxy - nothing to cycle here."
        # Migration safety net: if a pre-refactor :8443 orphan is still bound
        # (from a deploy before KGC_TRUST_PROXY=1 took effect), retire it now so
        # the box really has one backend. Cheap no-op once none exists.
        _orphan=$(pgrep -f "uvicorn server:app .*--port ${TLS_PORT}( |$)" 2>/dev/null || true)
        if [ -n "$_orphan" ]; then
          echo "[+] Retiring orphan TLS uvicorn from a previous deploy (PIDs: $(echo $_orphan | tr '\n' ' '))..."
          kill $_orphan 2>/dev/null || true
          sleep 2
          _still=$(pgrep -f "uvicorn server:app .*--port ${TLS_PORT}( |$)" 2>/dev/null || true)
          [ -n "$_still" ] && kill -9 $_still 2>/dev/null || true
        fi
      fi

      sleep 2
      if kill -0 "$PID" 2>/dev/null; then
        echo "[✓] Zero-downtime reload complete! New workers spawned, active requests preserved."
        DISCORD_DIR="$(dirname "$0")"
        [ -x "$DISCORD_DIR/discord_notify.sh" ] && "$DISCORD_DIR/discord_notify.sh" "🔄 **Server reloaded!** Zero-downtime, no player disconnects." 1542559680361140386 &
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
    if [ "$TLS_LISTENER" != "0" ]; then
      pkill -f "uvicorn.*server:app.*--port ${TLS_PORT}" 2>/dev/null || true
    fi
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
[ -n "${KGC_TRUST_PROXY:-}" ] && export KGC_TRUST_PROXY

# Forwarded-IP headers are trustworthy only when a reverse proxy is the sole
# ingress. Binding the app to loopback makes that network invariant enforceable
# instead of relying on a deployment comment that can drift.
if [ "${KGC_TRUST_PROXY:-}" = "1" ] && [ "$BIND_HOST" != "127.0.0.1" ] && [ "$BIND_HOST" != "::1" ]; then
  echo "[!] KGC_TRUST_PROXY=1 requires KGC_BIND_HOST=127.0.0.1 or ::1" >&2
  exit 2
fi
export KGC_BIND_HOST="$BIND_HOST"

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
  echo "[+] Starting Gunicorn + Uvicorn Workers on ${BIND_HOST}:${HTTP_PORT} (Zero-Downtime Ready)..."
  nohup "$GUNICORN" server:app -c gunicorn_conf.py > /tmp/kgc_pub_http.log 2>&1 &
  P1=$!
  echo "$P1" > "$PID_FILE"
else
  echo "[!] gunicorn not found; falling back to standalone uvicorn..."
  nohup "$UVICORN" server:app --host "$BIND_HOST" --port "${HTTP_PORT}" > /tmp/kgc_pub_http.log 2>&1 &
  P1=$!
  echo "$P1" > "$PID_FILE"
fi

if [ "$TLS_LISTENER" = "0" ]; then
  echo "[i] TLS listener skipped (KGC_TRUST_PROXY=1): reverse proxy terminates TLS upstream to :${HTTP_PORT}."
  P2=""
elif [ -f key.pem ] && [ -f cert.pem ]; then
  echo "[+] HTTPS TLS server ${BIND_HOST}:${TLS_PORT}"
  nohup "$UVICORN" server:app --host "$BIND_HOST" --port "${TLS_PORT}" \
      --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/kgc_pub_tls.log 2>&1 &
  P2=$!
else
  echo "[!] cert.pem/key.pem missing - HTTPS not started (Cloudflare Tunnel or reverse proxy must terminate TLS)"
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
  [ -x "$DISCORD_DIR/discord_notify.sh" ] && "$DISCORD_DIR/discord_notify.sh" "🔄 **Server started/restarted!** PID: $P1" 1542559680361140386 &
  exit 0
fi

wait
