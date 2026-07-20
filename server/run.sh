#!/usr/bin/env bash
# Dev stack: game server on HTTP :8080 + TLS :8443, admin dashboard on :8081.
# Everything auto-reloads on source AND data edits - no manual restart after editing
# server.py, dashboard.py, data/*.json or xml_live/*.xml. The dashboard's webui/ is
# static and served from disk, so front-end edits need only a browser refresh.
set -euo pipefail
cd "$(dirname "$0")"

# Emulator/device serial. redroid defaults to localhost:5556 (matches dashboard.py);
# override for BlueStacks/LDPlayer/real phone: ADB_SERIAL=127.0.0.1:5555 ./run.sh
ADB_SERIAL="${ADB_SERIAL:-localhost:5556}"

stop() {
    pkill -f "uvicorn server:app" 2>/dev/null || true
    pkill -f "uvicorn dashboard:app" 2>/dev/null || true
}

# Wire the device to the local server: connect, route its :443/:80 to our TLS/HTTP
# ports, and clear any leftover global proxy (a stale one on a fresh redroid blackholes
# every request). adb reverse is per-connection, so this must re-run after the emulator
# restarts - hence `run.sh device`. All non-fatal: no device = servers still come up.
wire_device() {
    if ! command -v adb >/dev/null 2>&1; then
        echo "[device] adb not on PATH - skipping device wiring"; return 0
    fi
    adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
    if ! adb -s "$ADB_SERIAL" get-state >/dev/null 2>&1; then
        echo "[device] $ADB_SERIAL not connected - skipping (start emulator, then: ./run.sh device)"
        return 0
    fi
    adb -s "$ADB_SERIAL" reverse tcp:443 tcp:8443 >/dev/null 2>&1 || true
    adb -s "$ADB_SERIAL" reverse tcp:80  tcp:8080 >/dev/null 2>&1 || true
    adb -s "$ADB_SERIAL" shell settings put global http_proxy :0 >/dev/null 2>&1 || true
    echo "[ok] device    $ADB_SERIAL  ->  :443→:8443  :80→:8080  proxy cleared"
}

# run.sh stop        -> kill the stack and exit
# run.sh device      -> (re)wire the emulator only, e.g. after it restarts
# run.sh restart|""  -> (re)start; start already kills any running copy first
case "${1:-}" in
    stop)    stop; echo "[stopped] game + dashboard"; exit 0 ;;
    device)  wire_device; exit 0 ;;
    restart|start|"") ;;
    *) echo "usage: run.sh [start|stop|restart|device]" >&2; exit 2 ;;
esac

RELOAD=(--reload
        --reload-dir . --reload-dir xml_live
        --reload-include '*.py' --reload-include '*.json' --reload-include '*.xml'
        --reload-exclude 'state/*')   # state/ is written by the server itself - watching it = restart loop

stop   # kill any running copy before relaunching
sleep 1

uvicorn server:app --host 0.0.0.0 --port 8080 "${RELOAD[@]}" >/tmp/kgc_server.log 2>&1 &
uvicorn server:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem \
        "${RELOAD[@]}" >/tmp/kgc_server_tls.log 2>&1 &
uvicorn dashboard:app --host 0.0.0.0 --port 8081 "${RELOAD[@]}" >/tmp/kgc_dashboard.log 2>&1 &

sleep 4
grep -q "Application startup complete" /tmp/kgc_server.log     && echo "[ok] http      :8080"
grep -q "Application startup complete" /tmp/kgc_server_tls.log && echo "[ok] https     :8443"
grep -q "Application startup complete" /tmp/kgc_dashboard.log  && echo "[ok] dashboard :8081  ->  http://127.0.0.1:8081"
wire_device
echo "logs: /tmp/kgc_server.log /tmp/kgc_server_tls.log /tmp/kgc_dashboard.log"
