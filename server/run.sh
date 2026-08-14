#!/usr/bin/env bash
# Dev stack: game server on HTTP :8080 + TLS :8443, admin API on :8081, next.js on :3000
# Everything auto-reloads on source AND data edits - no manual restart after editing
# server.py, dashboard.py, data/*.json or xml_live/*.xml. The Next.js frontend is
# served locally on :3000 during dev.
set -euo pipefail
cd "$(dirname "$0")"

# Prefer the repo venv (requirements.txt installs there) over whatever `uvicorn` a
# distro Python happens to expose. Falls back to PATH so an existing setup keeps
# working with no venv at all.
UVICORN="uvicorn"
for cand in "../.venv/bin/uvicorn" ".venv/bin/uvicorn"; do
    if [ -x "$cand" ]; then UVICORN="$(cd "$(dirname "$cand")" && pwd)/$(basename "$cand")"; break; fi
done

stop() {
    pkill -f "uvicorn server:app" 2>/dev/null || true
    pkill -f "uvicorn dashboard:app" 2>/dev/null || true
    pkill -f "next dev" 2>/dev/null || true
}

# run.sh stop        -> kill the stack and exit
# run.sh restart|""  -> (re)start; start already kills any running copy first
case "${1:-}" in
    stop)    stop; echo "[stopped] game + dashboard"; exit 0 ;;
    restart|start|"") ;;
    *) echo "usage: run.sh [start|stop|restart]" >&2; exit 2 ;;
esac

RELOAD=(--reload
        --reload-dir . --reload-dir xml_live
        --reload-include '*.py' --reload-include '*.json' --reload-include '*.xml'
        --reload-exclude "$PWD/state" --reload-exclude "$PWD/webui-next")   # state/ is written by the server itself - watching it = restart loop

stop   # kill any running copy before relaunching
sleep 1

nohup "$UVICORN" server:app --host 0.0.0.0 --port 8080 "${RELOAD[@]}" >/tmp/kgc_server.log 2>&1 &
nohup "$UVICORN" server:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem \
        "${RELOAD[@]}" >/tmp/kgc_server_tls.log 2>&1 &
nohup "$UVICORN" dashboard:app --host 0.0.0.0 --port 8081 "${RELOAD[@]}" >/tmp/kgc_dashboard.log 2>&1 &
if [ -d "webui-next" ]; then
    (cd webui-next && nohup npm run dev > /tmp/kgc_nextjs.log 2>&1 &)
fi

sleep 4
grep -q "Application startup complete" /tmp/kgc_server.log     && echo "[ok] http      :8080"
grep -q "Application startup complete" /tmp/kgc_server_tls.log && echo "[ok] https     :8443"
grep -q "Application startup complete" /tmp/kgc_dashboard.log  && echo "[ok] admin API :8081  ->  http://127.0.0.1:8081"
if [ -d "webui-next" ]; then
    echo "[ok] next.js   :3000  ->  http://127.0.0.1:3000"
fi
echo "python:   $UVICORN"
echo "logs: /tmp/kgc_server.log /tmp/kgc_server_tls.log /tmp/kgc_dashboard.log /tmp/kgc_nextjs.log"
wait
