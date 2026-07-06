#!/usr/bin/env bash
# check_notices.sh - Check KGC official notices from Notion per language
# Usage: ./check_notices.sh [--quiet]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/ntfy_send.sh"

NOTICES_HELPER="$SCRIPT_DIR/lib/notices_helper.py"

QUIET=false
[[ "${1:-}" == "--quiet" ]] && QUIET=true

log() { $QUIET || echo "$@" >&2; }

FETCH_SCRIPT="$PROJECT_DIR/scripts/fetch_notices.py"
HAS_NEW=false

check_lang_notices() {
    local lang="$1"
    local state_key="last_notices_${lang}"
    local output
    output=$(python3 "$FETCH_SCRIPT" "$lang" 2>/dev/null) || return 1

    local last_ids
    last_ids=$(state_json_read "$state_key")
    # First run (no state): seed all current notices as seen, don't notify -
    # otherwise the 20 most-recent notices would all fire as "new".
    local seed=false
    [[ "$last_ids" == "{}" ]] && seed=true

    local new_ids_file
    new_ids_file=$(mktemp)
    trap "rm -f $new_ids_file" RETURN

    local found_any=false

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        local page_id
        local notice_title
        # fetch_notices.py emits "<date>  <pageid>  <title>" (double-space).
        # awk collapses runs: $1=date $2=pageid, rest=title.
        page_id=$(echo "$line" | awk '{print $2}')
        notice_title=$(echo "$line" | awk '{$1="";$2="";sub(/^ +/,"");print}')

        local exists
        exists=$(echo "$last_ids" | python3 "$NOTICES_HELPER" check "$page_id" 2>/dev/null)
        [[ "$exists" == "true" ]] && continue

        found_any=true
        echo "$page_id" >> "$new_ids_file"

        $seed && continue   # seeding: record id, skip notification

        local body
        body=$(python3 "$FETCH_SCRIPT" "$page_id" 2>/dev/null) || body="(could not fetch notice body)"

        # fetch_notices dumps every block incl. image filenames + "Go Back" nav;
        # drop those for a clean preview, keep first 3 real lines.
        local excerpt
        excerpt=$(echo "$body" \
            | grep -viE '\.(png|gif|jpe?g)$|Go Back to List' \
            | grep -vE '^[[:space:]]*$' | head -3 || true)

        local notice_url="https://kgcastle-notice.awesomepiece.com/${page_id}"
        local notice_text
        notice_text=$(printf '**%s**\n\n%s\n\n[Read full notice ↗](%s)' \
            "$notice_title" "$excerpt" "$notice_url")

        python3 "$SCRIPT_DIR/lib/template_sender.py" "notices" "NOTICE" "loudspeaker" "$notice_url" \
            "notice_title=$notice_title" \
            "excerpt=$excerpt" \
            "notice_url=$notice_url"

        echo "NOTICE: [${lang}] $notice_title"
    done <<< "$output"

    if $found_any; then
        local updated_ids
        updated_ids=$(python3 "$NOTICES_HELPER" merge "$last_ids" "$new_ids_file" 2>/dev/null || echo "{}")
        state_json_write "$state_key" "$updated_ids"
        if $seed; then
            log "[check_notices] Seeded $lang state (no notifications on first run)"
            echo "none"
        else
            echo "new"
        fi
    else
        echo "none"
    fi
}

log "[check_notices] Checking notices..."
if [[ "$(check_lang_notices "en" || true)" == "new" ]]; then
    HAS_NEW=true
fi

if ! $HAS_NEW; then
    log "[check_notices] No new notices"
fi

log "[check_notices] Done"
