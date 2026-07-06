#!/usr/bin/env bash
# check_patch.sh - Check KGC CDN for new patch, notify per-language
# Usage: ./check_patch.sh [--quiet]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/ntfy_send.sh"

QUIET=false
[[ "${1:-}" == "--quiet" ]] && QUIET=true

log() { $QUIET || echo "$@" >&2; }

CDN_BASE="https://kgc-cdn-1.awesomepiece.com"
CDN_URL="${CDN_BASE}/?prefix=patch/LIVE/&delimiter=/"
STATE_KEY="last_patch"

raw_xml=$(curl -sf --max-time 15 "$CDN_URL") || {
    log "[check_patch] Failed to fetch CDN listing"
    exit 1
}

all_dates=$(python3 -c "
import sys, xml.etree.ElementTree as ET
root = ET.fromstring(sys.stdin.read())
ns = {'s3': 'http://doc.s3.amazonaws.com/2006-03-01'}
prefixes = [p.text for p in root.findall('.//s3:CommonPrefixes/s3:Prefix', ns)]
dates = []
for p in prefixes:
    parts = p.strip('/').split('/')
    if len(parts) >= 3 and parts[0] == 'patch' and parts[1] == 'LIVE':
        dates.append(parts[2])
for d in sorted(dates):
    print(d)
" <<< "$raw_xml")

if [[ -z "$all_dates" ]]; then
    log "[check_patch] No patch dates found on CDN"
    exit 1
fi

latest=$(echo "$all_dates" | tail -1)
last=$(state_read "$STATE_KEY")

if [[ "$latest" == "$last" ]]; then
    log "[check_patch] No new patch (latest: $latest)"
    exit 0
fi

latest_fmt=$(date_format "$latest")
last_fmt=""
days_diff=""
if [[ -n "$last" ]]; then
    last_fmt=$(date_format "$last")
    last_epoch=$(date_to_epoch "$last")
    latest_epoch=$(date_to_epoch "$latest")
    if [[ "$last_epoch" -gt 0 && "$latest_epoch" -gt 0 ]]; then
        days_diff=$(( (latest_epoch - last_epoch) / 86400 ))
    fi
fi

log "[check_patch] New patch detected: ${last:-none} → $latest"

patch_url="$CDN_BASE/patch/LIVE/$latest/"
title="📦 KGC Patch · $latest_fmt"

python3 "$SCRIPT_DIR/lib/template_sender.py" "patch" "PATCH" "package" "" \
    "latest_fmt=$latest_fmt" \
    "last_fmt=${last_fmt:-}" \
    "days_diff=${days_diff:-}"

state_write "$STATE_KEY" "$latest"
log "[check_patch] Done"
