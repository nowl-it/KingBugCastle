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

# Inject real Google OAuth client for public testing. Google requires a HTTPS domain.
export GLOGIN_PUBLIC_URL="https://kingbugcastle.id.vn"


# Prefer the repo venv, same as run.sh.
UVICORN="uvicorn"
for cand in "../.venv/bin/uvicorn" ".venv/bin/uvicorn"; do
  if [ -x "$cand" ]; then UVICORN="$(cd "$(dirname "$cand")" && pwd)/$(basename "$cand")"; break; fi
done
PY_BIN="${UVICORN%/uvicorn}/python"
[ -x "$PY_BIN" ] || PY_BIN="python3"

# Registration is open by definition here: the client picks its own account id. Keep
# the caps explicit rather than relying on defaults nobody remembers.
export KGC_MAX_PLAYERS="${KGC_MAX_PLAYERS:-200}"
export KGC_NEW_PLAYER_PER_IP="${KGC_NEW_PLAYER_PER_IP:-5}"
export KGC_RATE_LIMIT="${KGC_RATE_LIMIT:-600}"
export KGC_RATE_BAN_AFTER="${KGC_RATE_BAN_AFTER:-5}"
export KGC_RATE_BAN_SECONDS="${KGC_RATE_BAN_SECONDS:-900}"
# Firewall-hardening: repeated 429s also get dropped by iptables for the ban
# duration. OFF by default - it needs a VALID sudoers rule for the service user
# (a comma in the command spec is a sudoers list separator and fail-closes the
# whole sudoers include - the 2026-07-31 outage). App-level ban is enough.
#   ubuntu ALL=(root) NOPASSWD: /usr/sbin/iptables -I INPUT 1 -s * -j DROP
#   ubuntu ALL=(root) NOPASSWD: /usr/sbin/iptables -D INPUT -s * -j DROP
export KGC_IPTABLES_BAN="${KGC_IPTABLES_BAN:-0}"
export KGC_MAX_BODY="${KGC_MAX_BODY:-1000000}"
# One echoed line per request is an unbounded log file on a server that runs for
# weeks. The dashboard's log view keeps working - that buffer is capped and in memory.
export KGC_QUIET="${KGC_QUIET:-1}"
[ -n "${KGC_ADMIN_TOKEN:-}" ] && export KGC_ADMIN_TOKEN
[ -n "${KGC_TRUST_PROXY:-}" ] && export KGC_TRUST_PROXY

# Every "is this safe to expose" rule lives in preflight.py, not here - one place to
# read, one place to add to, and an operator can run it without starting anything.
# It covers the admin credential, the dev login bypass, the abuse caps, the database,
# master data and the CDN bundles.
echo "[+] preflight"
if ! "$PY_BIN" preflight.py; then
  echo ""
  echo "[!] refusing to serve publicly. Fix the FAIL lines above, then re-run."
  exit 1
fi
echo ""

echo "[+] HTTP  server  0.0.0.0:${HTTP_PORT}"
"$UVICORN" server:app --host 0.0.0.0 --port "${HTTP_PORT}" > /tmp/kgc_pub_http.log 2>&1 &
P1=$!

if [ -f key.pem ] && [ -f cert.pem ]; then
  echo "[+] HTTPS server  0.0.0.0:${TLS_PORT}  (self-signed; SSL-bypass patch accepts it)"
  "$UVICORN" server:app --host 0.0.0.0 --port "${TLS_PORT}" \
      --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/kgc_pub_tls.log 2>&1 &
  P2=$!
else
  echo "[!] cert.pem/key.pem missing - HTTPS not started (fine if you use a Cloudflare Tunnel)"
  P2=""
fi

echo ""
echo "  HTTP  :${HTTP_PORT}  PID ${P1}   (point a tunnel here, or forward :80)"
[ -n "${P2}" ] && echo "  HTTPS :${TLS_PORT}  PID ${P2}   (forward external :443 here for IP-based hosting)"
echo ""
echo "  Dashboard (admin + tracker):  $PY_BIN dashboard.py   -> http://localhost:8081"
echo "  Stop:  kill ${P1} ${P2}"
echo ""
echo "  Reminder: the baked host in the XAPK must resolve to THIS machine on :443"
echo "  (tunnel hostname, public IP, or LAN IP). Rebuild the XAPK if the host changes:"
echo "    SHARE_HOST=<host> python3 rebuild_arm64_mod.py --share"
wait
