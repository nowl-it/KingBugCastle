#!/usr/bin/env bash
# KGC CDN update checker - cron daily 0h
# Queries CDN S3 bucket for latest patch date, notifies if new.
# Enhanced: shows all dates, file counts, XML diff summary, local state comparison.

set -euo pipefail

CDN_BASE="https://kgc-cdn-1.awesomepiece.com"
CDN_URL="${CDN_BASE}/?prefix=patch/LIVE/&delimiter=/"
STATE_FILE="$HOME/.local/share/kgc_cdn_last_date"
NTFY_TOPIC="https://ntfy.sh/nowl/test"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

mkdir -p "$(dirname "$STATE_FILE")"

# ─── Fetch CDN S3 listing ────────────────────────────────────────
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     KGC CDN Update Checker                  ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

raw_xml=$(curl -sf "$CDN_URL") || {
    echo -e "${RED}[✗] Failed to fetch CDN listing from ${CDN_URL}${NC}" >&2
    exit 1
}

# Parse all LIVE patch dates from S3 listing
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
    echo -e "${RED}[✗] No patch dates found in CDN listing${NC}" >&2
    exit 1
fi

latest=$(echo "$all_dates" | tail -1)
total_count=$(echo "$all_dates" | wc -l)

# ─── CDN Patch History ───────────────────────────────────────────
echo -e "${CYAN}── CDN Patch History ──${NC}"
echo -e "${DIM}Total patches on CDN: ${NC}${BOLD}${total_count}${NC}"
echo ""

# Show last 10 dates with markers
echo "$all_dates" | tail -10 | while read -r d; do
    marker=""
    if [[ "$d" == "$latest" ]]; then
        marker=" ${GREEN}◀ latest${NC}"
    fi
    # Convert underscore date to readable format
    readable=$(echo "$d" | sed 's/_/-/g')
    echo -e "  ${DIM}•${NC} ${readable}${marker}"
done

if [[ "$total_count" -gt 10 ]]; then
    hidden=$((total_count - 10))
    echo -e "  ${DIM}  ... and ${hidden} older patches${NC}"
fi
echo ""

# ─── Local State Comparison ──────────────────────────────────────
echo -e "${CYAN}── Local State ──${NC}"

last=""
if [[ -f "$STATE_FILE" ]]; then
    last=$(cat "$STATE_FILE")
fi

echo -e "  Last checked date:  ${BOLD}${last:-"(none)"}${NC}"
echo -e "  CDN latest date:    ${BOLD}${latest}${NC}"

# Check local IOS snapshots
local_dates=""
if [[ -d "$PROJECT_DIR/IOS" ]]; then
    local_dates=$(ls -1 "$PROJECT_DIR/IOS" 2>/dev/null | grep -E '^[0-9]{4}_[0-9]{2}_[0-9]{2}$' | sort)
fi
local_latest=""
if [[ -n "$local_dates" ]]; then
    local_latest=$(echo "$local_dates" | tail -1)
    local_count=$(echo "$local_dates" | wc -l)
    echo -e "  Local IOS snapshots: ${BOLD}${local_count}${NC} (latest: ${local_latest})"
else
    echo -e "  Local IOS snapshots: ${DIM}(none)${NC}"
fi

# Check server PATCH_FOLDER
server_patch=""
if [[ -f "$PROJECT_DIR/server/server.py" ]]; then
    server_patch=$(grep -oP 'PATCH_FOLDER\s*=\s*"([^"]+)"' "$PROJECT_DIR/server/server.py" | grep -oP '"[^"]+"' | tr -d '"')
    echo -e "  Server PATCH_FOLDER: ${BOLD}${server_patch:-"(not set)"}${NC}"
fi

echo ""

# ─── Update Detection ───────────────────────────────────────────
if [[ "$latest" == "$last" ]]; then
    echo -e "${GREEN}[✓] No update. CDN is at: ${latest}${NC}"
    echo ""

    # Collect staleness warnings
    stale_warnings=()
    if [[ -n "$local_latest" && "$local_latest" != "$latest" ]]; then
        echo -e "${YELLOW}[!] Local IOS snapshot (${local_latest}) is behind CDN (${latest})${NC}"
        echo -e "    Run: ${DIM}./kgc-cli download${NC} to fetch latest data"
        stale_warnings+=("⚠ IOS snapshot outdated: ${local_latest} → ${latest}")
    fi
    if [[ -n "$server_patch" && "$server_patch" != "$latest" ]]; then
        echo -e "${YELLOW}[!] Server PATCH_FOLDER (${server_patch}) is behind CDN (${latest})${NC}"
        echo -e "    Update PATCH_FOLDER in server/server.py"
        stale_warnings+=("⚠ Server PATCH_FOLDER outdated: ${server_patch} → ${latest}")
    fi

    # Send local desktop notification if there are staleness warnings
    if [[ ${#stale_warnings[@]} -gt 0 ]]; then
        if command -v notify-send &>/dev/null; then
            DISPLAY="${DISPLAY:-:0}" notify-send -u normal -a "KGC Watcher" \
                "KGC: Local data outdated" \
                "$(printf '%s\n' "${stale_warnings[@]}")" &
        fi
    fi
    exit 0
fi

# ─── New Patch Detected ─────────────────────────────────────────
echo -e "${GREEN}${BOLD}[★] NEW PATCH DETECTED: ${last:-"(first run)"} → ${latest}${NC}"
echo "$latest" > "$STATE_FILE"
echo ""

# Calculate days since last patch
if [[ -n "$last" ]]; then
    last_epoch=$(date -d "$(echo "$last" | tr '_' '-')" +%s 2>/dev/null || echo "0")
    latest_epoch=$(date -d "$(echo "$latest" | tr '_' '-')" +%s 2>/dev/null || echo "0")
    if [[ "$last_epoch" -gt 0 && "$latest_epoch" -gt 0 ]]; then
        days_diff=$(( (latest_epoch - last_epoch) / 86400 ))
        echo -e "  Days since last patch: ${BOLD}${days_diff}${NC}"
    fi
fi

# ─── Probe CDN for file listing in new patch ─────────────────────
echo ""
echo -e "${CYAN}── New Patch Contents (probe) ──${NC}"

for platform in ANDROID IOS; do
    xml_prefix="patch/LIVE/${latest}/${platform}/xml/ExportedProject/Assets/patchresources/datas/"
    probe_url="${CDN_BASE}/?prefix=${xml_prefix}&delimiter=/"

    file_listing=$(curl -sf "$probe_url" 2>/dev/null) || continue
    file_count=$(python3 -c "
import sys, xml.etree.ElementTree as ET
try:
    root = ET.fromstring(sys.stdin.read())
    ns = {'s3': 'http://doc.s3.amazonaws.com/2006-03-01'}
    contents = root.findall('.//s3:Contents', ns)
    keys = root.findall('.//s3:Key', ns)
    count = len(contents) if contents else len(keys)
    print(count)
except:
    print(0)
" <<< "$file_listing" 2>/dev/null)

    if [[ "${file_count:-0}" -gt 0 ]]; then
        echo -e "  ${platform}: ${BOLD}${file_count}${NC} files in XML data path"
    else
        echo -e "  ${platform}: ${DIM}(no XML files found or listing not available)${NC}"
    fi
done

# ─── Staleness Warnings ─────────────────────────────────────────
echo ""
echo -e "${CYAN}── Action Items ──${NC}"

needs_action=false

if [[ -n "$local_latest" && "$local_latest" != "$latest" ]]; then
    echo -e "  ${YELLOW}▸${NC} Download new IOS XML snapshot:"
    echo -e "    ${DIM}./kgc-cli download${NC}"
    needs_action=true
fi

if [[ -n "$server_patch" && "$server_patch" != "$latest" ]]; then
    echo -e "  ${YELLOW}▸${NC} Update server/server.py PATCH_FOLDER:"
    echo -e "    ${DIM}sed -i 's/PATCH_FOLDER = \"${server_patch}\"/PATCH_FOLDER = \"${latest}\"/' server/server.py${NC}"
    needs_action=true
fi

echo -e "  ${YELLOW}▸${NC} Compare with previous patch:"
if [[ -n "$last" ]]; then
    echo -e "    ${DIM}./kgc-cli compare ${last} ${latest}${NC}"
else
    echo -e "    ${DIM}./kgc-cli compare <old_date> ${latest}${NC}"
fi
needs_action=true

if ! $needs_action; then
    echo -e "  ${GREEN}Everything up to date.${NC}"
fi

# ─── Notifications ───────────────────────────────────────────────
echo ""

title="🏰 Cập nhật CDN King God Castle"
latest_fmt=$(echo "$latest" | sed 's/_/-/g')

# Build rich ntfy body for community
ntfy_body="Phát hiện bản cập nhật mới trên CDN!\n\n"
ntfy_body+="📅 Phiên bản mới: ${latest_fmt} (${latest})\n"

if [[ -n "$last" ]]; then
    last_fmt=$(echo "$last" | sed 's/_/-/g')
    ntfy_body+="⏮️ Phiên bản trước: ${last_fmt} (${last})\n"
    # Days since last
    last_epoch=$(date -d "$(echo "$last" | tr '_' '-')" +%s 2>/dev/null || echo "0")
    latest_epoch=$(date -d "$(echo "$latest" | tr '_' '-')" +%s 2>/dev/null || echo "0")
    if [[ "$last_epoch" -gt 0 && "$latest_epoch" -gt 0 ]]; then
        d=$(( (latest_epoch - last_epoch) / 86400 ))
        ntfy_body+="⏱️ Khoảng cách: ${d} ngày\n"
    fi
fi

# Append file counts from CDN probe
has_counts=false
counts_text=""
for platform in ANDROID IOS; do
    xml_prefix="patch/LIVE/${latest}/${platform}/xml/ExportedProject/Assets/patchresources/datas/"
    probe_url="${CDN_BASE}/?prefix=${xml_prefix}&delimiter=/"
    fc=$(curl -sf "$probe_url" 2>/dev/null | python3 -c "
import sys, xml.etree.ElementTree as ET
try:
    root = ET.fromstring(sys.stdin.read())
    ns = {'s3': 'http://doc.s3.amazonaws.com/2006-03-01'}
    c = root.findall('.//s3:Contents', ns)
    k = root.findall('.//s3:Key', ns)
    print(len(c) if c else len(k))
except:
    print(0)
" 2>/dev/null)
    if [[ "${fc:-0}" -gt 0 ]]; then
        if ! $has_counts; then
            counts_text+="\n📊 Số lượng file XML thay đổi:\n"
            has_counts=true
        fi
        counts_text+="  • ${platform}: ${fc} tệp tin\n"
    fi
done
ntfy_body+="${counts_text}"

# Desktop notification (non-blocking)
desktop_msg="New patch: ${latest}"
if [[ -n "$last" ]]; then
    desktop_msg="${last} → ${latest}"
fi
if command -v notify-send &>/dev/null; then
    DISPLAY="${DISPLAY:-:0}" notify-send -u critical -a "KGC Watcher" "🏰 KGC CDN Update" "$desktop_msg" &
fi

# ntfy.sh push
curl -sf \
    -H "Title: $title" \
    -H "Tags: game,kgc,update,new" \
    -H "Priority: urgent" \
    -H "Actions: view, Mở CDN, ${CDN_BASE}/patch/LIVE/${latest}/, clear=true" \
    -d "$(echo -e "$ntfy_body")" \
    "$NTFY_TOPIC" &>/dev/null \
    && echo -e "${GREEN}[✓] Notifications sent (ntfy + desktop).${NC}" \
    || echo -e "${DIM}[ntfy] Push notification failed (network?)${NC}"
