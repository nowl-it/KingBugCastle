#!/usr/bin/env bash
# Bundle patched "King Bug Castle" client + server into one shareable zip.
# Run AFTER deploy.sh (produces signed APKs in .deploy/) OR rebuild_arm64.py.
# Usage: ./make_share.sh [--arm64]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$ROOT/KingBugCastle_share"
ZIP="$ROOT/KingBugCastle_share.zip"
MODE="${1:-32bit}"

rm -rf "$OUT" "$ZIP"
mkdir -p "$OUT/apk" "$OUT/server"

# ---- APKs ----
if [ "$MODE" = "--arm64" ]; then
    REBUILD="$ROOT/.rebuild3"
    for f in base.apk config.arm64_v8a.apk base_assets.apk; do
        [ -f "$REBUILD/$f" ] || { echo "[✗] missing $REBUILD/$f — run rebuild_arm64.py first" >&2; exit 1; }
    done
    cp "$REBUILD"/{base.apk,config.arm64_v8a.apk,base_assets.apk} "$OUT/apk/"
    echo "[+] arm64 APKs bundled"
else
    DEPLOY="$ROOT/.deploy"
    for f in base_signed.apk split_base_assets_signed.apk split_config_signed.apk; do
        [ -f "$DEPLOY/$f" ] || { echo "[✗] missing $DEPLOY/$f — run deploy.sh first" >&2; exit 1; }
    done
    cp "$DEPLOY"/{base_signed,split_base_assets_signed,split_config_signed}.apk "$OUT/apk/"
    echo "[+] 32-bit APKs bundled"
fi

# ---- Server code ----
cp "$SCRIPT_DIR/server.py" "$SCRIPT_DIR/tls_proxy.py" "$OUT/server/"
cp -r "$SCRIPT_DIR/generated" "$SCRIPT_DIR/state" "$SCRIPT_DIR/certs" "$OUT/server/"
cp "$SCRIPT_DIR/../README_PLAYER.md" "$OUT/README.md" 2>/dev/null || true

cat > "$OUT/start.sh" <<'SHEOF'
#!/usr/bin/env bash
# King Bug Castle private server
# Usage: sudo ./start.sh
set -euo pipefail
cd "$(dirname "$0")/server"

echo "[+] Starting HTTP server on port 80..."
python3 -m uvicorn server:app --host 0.0.0.0 --port 80 &
PID1=$!

sleep 1

echo "[+] Starting TLS proxy on port 443 → 80..."
python3 tls_proxy.py --port 443 --upstream 127.0.0.1:80 &
PID2=$!

echo ""
echo "  Server  (HTTP)  :80   PID $PID1"
echo "  TLS proxy (HTTPS):443  PID $PID2"
echo ""
echo "Stop: kill $PID1 $PID2"
echo ""

trap "kill $PID1 $PID2 2>/dev/null; exit" SIGINT SIGTERM
wait
SHEOF
chmod +x "$OUT/start.sh"

# ---- hosts template for device ----
cat > "$OUT/hosts_template.txt" <<'EOF'
# KGC private server — add these lines to your device's /etc/hosts (root required)
127.0.0.1 axis-game.awesomepiece.com
127.0.0.1 kgc-k8s-1.awesomepiece.com
127.0.0.1 isekai-lobbyserver.awesomepiece.com
127.0.0.1 kgc-cdn-1.awesomepiece.com
127.0.0.1 castle-infra-server-xxxxxxxxx-uc.a.run.app
EOF

( cd "$ROOT" && zip -qr "$ZIP" "$(basename "$OUT")" )
echo "[+] bundle: $ZIP"
du -sh "$ZIP"
