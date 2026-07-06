#!/usr/bin/env bash
# ntfy_send.sh - Send notification to ntfy topic
# Usage: ntfy_send <topic> <title> <message> [tags] [priority] [click]
# Body is rendered as Markdown (ntfy "Markdown: yes"). Pass real newlines.
set -euo pipefail

NOTI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$NOTI_DIR/config.sh"

ntfy_send() {
    local topic="$1"
    local title="$2"
    local message="$3"
    local tags="${4:-info}"
    local priority="${5:-default}"
    local click="${6:-}"

    local url="$NTFY_SERVER/$topic"

    local hdrs=(-H "Markdown: yes")
    [[ -n "${NTFY_TOKEN:-}" ]] && hdrs+=(-H "Authorization: Bearer $NTFY_TOKEN")
    [[ -n "$click" ]] && hdrs+=(-H "Click: $click")

    curl -sf \
        "${hdrs[@]}" \
        -H "Title: $title" \
        -H "Tags: $tags" \
        -H "Priority: $priority" \
        --data-binary "$message" \
        "$url" &>/dev/null
}

ntfy_send_summary() {
    local title="$1"
    local body="$2"
    local tags="${3:-info}"
    local click="${4:-}"
    ntfy_send "$SUMMARY_TOPIC" "$title" "$body" "$tags" "default" "$click"
}

# ntfy_send_lang and ntfy_send_all_langs removed. Use template_sender.py instead.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ $# -lt 3 ]]; then
        echo "Usage: $0 <topic> <title> <message> [tags] [priority] [click]" >&2
        exit 1
    fi
    ntfy_send "$@"
fi
