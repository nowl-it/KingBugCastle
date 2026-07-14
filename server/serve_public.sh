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

echo "[+] HTTP  server  0.0.0.0:${HTTP_PORT}"
uvicorn server:app --host 0.0.0.0 --port "${HTTP_PORT}" > /tmp/kgc_pub_http.log 2>&1 &
P1=$!

if [ -f key.pem ] && [ -f cert.pem ]; then
  echo "[+] HTTPS server  0.0.0.0:${TLS_PORT}  (self-signed; SSL-bypass patch accepts it)"
  uvicorn server:app --host 0.0.0.0 --port "${TLS_PORT}" \
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
echo "  Dashboard (admin + tracker):  python3 dashboard.py   -> http://localhost:8081"
echo "  Stop:  kill ${P1} ${P2}"
echo ""
echo "  Reminder: the baked host in the XAPK must resolve to THIS machine on :443"
echo "  (tunnel hostname, public IP, or LAN IP). Rebuild the XAPK if the host changes:"
echo "    SHARE_HOST=<host> python3 rebuild_arm64_mod.py --share"
wait
