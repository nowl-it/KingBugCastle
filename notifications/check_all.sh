#!/usr/bin/env bash
# check_all.sh - Master orchestrator for KGC notification system
# Runs all checks and publishes summary. Call from cron every 6h.
# Usage: ./check_all.sh [--test]
#   --test: Sends all notifications to a single 'nowl-test' topic for easy debugging

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/ntfy_send.sh"

SUMMARY_ITEMS=()
SUMMARY_TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
SUMMARY_FILE=$(mktemp)
trap "rm -f $SUMMARY_FILE" EXIT

if [[ "${1:-}" == "--test" ]]; then
    export TEST_MODE="true"
    echo "[check_all] Running in TEST MODE (all topics redirected to nowl-test)"
fi

echo "[check_all] Starting KGC notification run at $SUMMARY_TS"
echo ""

# ─── Step 1: Check Patch ───────────────────────────────────────────
echo "=== Step 1/3: CDN Patch Check ==="
PATCH_OUT=$("$SCRIPT_DIR/check_patch.sh" --quiet 2>&1) || true
echo "$PATCH_OUT"
if echo "$PATCH_OUT" | grep -q "New patch detected"; then
    LATEST_PATCH=$(echo "$PATCH_OUT" | grep -oP 'New patch detected:.*→ \K\S+' || echo "unknown")
    SUMMARY_ITEMS+=("📦 Patch: $LATEST_PATCH")
fi
echo ""

# ─── Step 2: Check App Store versions ─────────────────────────────
echo "=== Step 2/3: App Store Version Check ==="
STORE_OUT=$("$SCRIPT_DIR/check_appstore.sh" --quiet 2>&1) || true
echo "$STORE_OUT"
while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    platform=$(echo "$line" | grep -oP '(?<=\[)\w+(?=\])')
    ver=$(echo "$line" | grep -oP 'v\S+')
    icon=$([[ "$platform" == "android" ]] && echo "🤖" || echo "🍎")
    SUMMARY_ITEMS+=("${icon} ${platform^}: ${ver}")
done < <(echo "$STORE_OUT" | grep '^UPDATE:' || true)
echo ""

# ─── Step 3: Check Notices ─────────────────────────────────────────
echo "=== Step 3/3: Notices Check ==="
NOTICES_OUT=$("$SCRIPT_DIR/check_notices.sh" --quiet 2>&1) || true
echo "$NOTICES_OUT"
NOTICE_LINES=$(echo "$NOTICES_OUT" | grep -oP '^NOTICE:.*' || true)
if [[ -n "$NOTICE_LINES" ]]; then
    while IFS= read -r line; do
        SUMMARY_ITEMS+=("$line")
    done <<< "$NOTICE_LINES"
    SUMMARY_ITEMS=("${SUMMARY_ITEMS[@]/#NOTICE: /}")
fi
echo ""

# ─── Step 3: Send Summary ──────────────────────────────────────────
if [[ ${#SUMMARY_ITEMS[@]} -eq 0 ]]; then
    SUMMARY_TITLE="🏰 KGC · No changes"
    SUMMARY_BODY="No new updates since last check."
    SUMMARY_TAGS="white_check_mark"
    echo "[check_all] No updates to report."
else
    SUMMARY_TITLE="🏰 KGC · ${#SUMMARY_ITEMS[@]} update(s)"
    SUMMARY_BODY=$(printf '**Updates detected**\n')
    for item in "${SUMMARY_ITEMS[@]}"; do
        SUMMARY_BODY+=$(printf '\n- %s' "$item")
    done
    SUMMARY_TAGS="bell"
    echo "[check_all] Sending summary with ${#SUMMARY_ITEMS[@]} update(s)..."
fi

SUMMARY_BODY+=$(printf '\n\n🕐 %s' "$SUMMARY_TS")

summary_topic="$SUMMARY_TOPIC"
[[ "${TEST_MODE:-}" == "true" ]] && summary_topic="nowl-test"

ntfy_send "$summary_topic" "$SUMMARY_TITLE" "$SUMMARY_BODY" "$SUMMARY_TAGS"

echo ""
echo "[check_all] Done at $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
