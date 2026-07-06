#!/usr/bin/env bash
# check_appstore.sh - Check KGC app version on Google Play + App Store
# Usage: ./check_appstore.sh [--quiet]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/ntfy_send.sh"

QUIET=false
[[ "${1:-}" == "--quiet" ]] && QUIET=true
log() { $QUIET || echo "$@" >&2; }

APP_ID="com.awesomepiece.castle"

check_platform() {
    local platform="$1"   # android | ios
    local state_key="last_version_${platform}"
    local version="$2"
    local store_url="$3"

    [[ -z "$version" ]] && { log "[check_appstore] Could not fetch $platform version"; return 1; }

    local last
    last=$(state_read "$state_key")

    if [[ "$version" == "$last" ]]; then
        log "[check_appstore] $platform unchanged ($version)"
        return 0
    fi

    log "[check_appstore] $platform: ${last:-none} → $version"

    local icon; [[ "$platform" == "android" ]] && icon="🤖" || icon="🍎"
    local tag;  [[ "$platform" == "android" ]] && tag="android" || tag="apple"
    local plat_name; [[ "$platform" == "ios" ]] && plat_name="IOS" || plat_name="Android"
    local title="${icon} KGC ${plat_name} · v${version}"

    python3 "$SCRIPT_DIR/lib/template_sender.py" "version" "APP" "$tag" "$store_url" \
        "platform=${plat_name}" \
        "icon=$icon" \
        "version=$version" \
        "last_version=${last:-}" \
        "store_url=$store_url"
    echo "UPDATE: [${platform}] v${version}"

    state_write "$state_key" "$version"
}

# ── Android / APKPure ──────────────────────────────────────────────────────
android_version=$(curl -sL --max-time 15 \
    -H "Accept-Language: en-US,en;q=0.9" \
    -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
    "https://apkpure.net/king-god-castle/${APP_ID}" \
  | python3 -c "
import sys, re
m = re.search(r'\"version\":\"(\d+\.\d+\.\d+)\"', sys.stdin.read())
print(m.group(1) if m else '')
" 2>/dev/null) || android_version=""

PLAY_URL="https://apkpure.net/king-god-castle/${APP_ID}"
check_platform "android" "$android_version" "$PLAY_URL" || true

# ── iOS / App Store ────────────────────────────────────────────────────────
ios_version=$(curl -s --max-time 15 \
    "https://itunes.apple.com/lookup?bundleId=${APP_ID}&country=kr" \
  | python3 -c "
import json, sys
r = json.load(sys.stdin).get('results', [])
print(r[0]['version'] if r else '')
" 2>/dev/null) || ios_version=""

IOS_URL="https://apps.apple.com/kr/app/id1475556207"
check_platform "ios" "$ios_version" "$IOS_URL" || true

log "[check_appstore] Done"
