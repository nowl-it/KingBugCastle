#!/usr/bin/env bash
# Long-running wrapper for the CDN checker.  Designed for kgc-cdn-monitor.service.
set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NOTIFY="$ROOT_DIR/server/discord_notify.sh"
CHECKER="$ROOT_DIR/scripts/check_cdn_update.sh"

"$NOTIFY" "🛰️ KGC CDN monitor online — checking every 30 minutes." || true

while true; do
    "$CHECKER" || echo "[$(date -Is)] CDN check failed; retrying in 30 minutes." >&2
    sleep 1800
done
