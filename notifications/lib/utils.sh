#!/usr/bin/env bash
# utils.sh - Shared utility functions for KGC notification system
set -euo pipefail

NOTI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$NOTI_DIR/config.sh"

state_read() {
    local key="$1"
    local file="$STATE_DIR/${key}.txt"
    if [[ -f "$file" ]]; then
        cat "$file"
    else
        echo ""
    fi
}

state_write() {
    local key="$1"
    local value="$2"
    local file="$STATE_DIR/${key}.txt"
    echo "$value" > "$file"
}

state_json_read() {
    local key="$1"
    local file="$STATE_DIR/${key}.json"
    if [[ -f "$file" ]]; then
        cat "$file"
    else
        echo "{}"
    fi
}

state_json_write() {
    local key="$1"
    local value="$2"
    local file="$STATE_DIR/${key}.json"
    echo "$value" > "$file"
}

date_to_epoch() {
    local date_str="$1"
    date -d "$(echo "$date_str" | tr '_' '-')" +%s 2>/dev/null || echo "0"
}

date_format() {
    local date_str="$1"
    echo "$date_str" | sed 's/_/-/g'
}

http_get_retry() {
    local url="$1"
    local max_retries="${2:-3}"
    local timeout="${3:-10}"
    local result=""
    for i in $(seq 1 "$max_retries"); do
        result=$(curl -sf --max-time "$timeout" "$url" 2>/dev/null) && echo "$result" && return 0
        sleep 1
    done
    return 1
}
