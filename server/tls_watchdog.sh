#!/usr/bin/env bash
# KGC TLS (:8443) liveness watchdog.
#
# Why this exists: serve_public.sh launches the :8443 uvicorn with `nohup &`, so
# it runs as an orphan (ppid=1) outside kgc.service's cgroup. kgc.service's
# Restart=on-failure therefore never covers it. When the OOM killer takes that
# process down, every game route breaks (Caddy reverse-proxies them all to
# :8443) while `systemctl status kgc` still reads "active". This probe turns a
# silent multi-hour outage into a <=2-minute auto-recovery.
#
# Deliberately does NOT call `serve_public.sh reload`: that path SIGKILLs the
# (possibly healthy) TLS process and respawns it, which races the port release
# (Errno 98 "address already in use") and needlessly SIGHUPs gunicorn. Here we
# only act when :8443 is confirmed dead, then start a fresh uvicorn directly.
#
# Invoked by systemd (kgc-tls-watchdog.timer). Safe to run manually.
set -u

SERVER_DIR="${SERVER_DIR:-/home/ubuntu/kgc/server}"
UVICORN="${UVICORN:-/home/ubuntu/kgc/.venv/bin/uvicorn}"
TLS_HOST="${TLS_HOST:-127.0.0.1}"
TLS_PORT="${TLS_PORT:-8443}"
TLS_PROBE="${TLS_PROBE:-https://127.0.0.1:8443/}"
PROBE_TRIES="${PROBE_TRIES:-3}"
PROBE_GAP="${PROBE_GAP:-3}"

healthy() {
    # A matching uvicorn process AND a listening socket on TLS_PORT together mean
    # the endpoint is alive, even if the single worker is currently backlogged.
    # The old curl-with-timeout probe treated "slow but serving" as "dead" and
    # SIGKILLed a working uvicorn during load spikes, causing the very restart
    # churn it was meant to prevent. Only a missing process or missing socket
    # counts as down.
    pgrep -f "uvicorn server:app .*--port ${TLS_PORT}( |$)" >/dev/null 2>&1 \
        && ss -ltn 2>/dev/null | grep -q ":${TLS_PORT} "
}

# Probe with retries so a transient blip (busy worker, slow TLS handshake) does
# not trigger a needless restart.
for i in $(seq 1 "$PROBE_TRIES"); do
    if healthy; then
        echo "[watchdog] :${TLS_PORT} healthy (try ${i}/${PROBE_TRIES})"
        exit 0
    fi
    sleep "$PROBE_GAP"
done

echo "[watchdog] :${TLS_PORT} confirmed down after ${PROBE_TRIES} tries - recovering"

# Clear any half-dead TLS procs by resolved PID (never pkill -f, whose regex
# would also match this very command line and kill our own session).
for p in $(pgrep -f "uvicorn server:app .*--port ${TLS_PORT}( |$)" 2>/dev/null || true); do
    [ "$p" = "$$" ] && continue
    kill -9 "$p" 2>/dev/null || true
done

# Wait for the port to actually free before binding again.
for _ in $(seq 1 10); do
    curl -s --max-time 2 -o /dev/null "https://${TLS_HOST}:${TLS_PORT}/" -w '%{http_code}' 2>/dev/null | grep -q 000 && break
    sleep 1
done

cd "$SERVER_DIR" || exit 1
setsid nohup "$UVICORN" server:app --host "$TLS_HOST" --port "$TLS_PORT" \
    --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/kgc_pub_tls.log 2>&1 < /dev/null &
echo "[watchdog] spawned TLS uvicorn (pid $!)"

# Verify before declaring success.
for _ in $(seq 1 20); do
    if healthy; then
        echo "[watchdog] :${TLS_PORT} recovered OK"
        exit 0
    fi
    sleep 1
done

echo "[watchdog] :${TLS_PORT} STILL DOWN after recovery - check /tmp/kgc_pub_tls.log"
tail -20 /tmp/kgc_pub_tls.log 2>/dev/null || true
exit 1
