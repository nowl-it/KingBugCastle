#!/usr/bin/env bash
# Capture only the iOS services relevant to KGC Apple-account authentication.
#
# Usage:
#   bash scripts/capture_ios_auth_logs.sh [output-directory]
#
# Connect and unlock one trusted iPhone over USB, start this command, reproduce
# the password prompt once, then press Ctrl-C.  The resulting log is redacted
# before it is written, but still treat it as private device diagnostics.
set -euo pipefail

readonly BUNDLE_ID="com.awesomepiece.castle"
readonly OUT_DIR="${1:-captures}"

for cmd in idevice_id idevicesyslog; do
    command -v "$cmd" >/dev/null || {
        echo "Missing $cmd. Install libimobiledevice, then reconnect the unlocked iPhone." >&2
        exit 1
    }
done

mapfile -t devices < <(idevice_id -l)
if (( ${#devices[@]} == 0 )); then
    echo "No trusted iPhone found. Connect it by USB, unlock it, and tap Trust." >&2
    exit 1
fi
if (( ${#devices[@]} > 1 )) && [[ -z "${IOS_UDID:-}" ]]; then
    printf 'More than one iPhone is connected; set IOS_UDID to one of:\n' >&2
    printf '  %s\n' "${devices[@]}" >&2
    exit 1
fi

readonly UDID="${IOS_UDID:-${devices[0]}}"
connected=false
for device in "${devices[@]}"; do
    [[ "$device" == "$UDID" ]] && connected=true
done
if [[ "$connected" != true ]]; then
    echo "IOS_UDID is not the connected device." >&2
    exit 1
fi

mkdir -p "$OUT_DIR"
readonly OUT_FILE="$OUT_DIR/kgc-ios-auth-$(date -u +%Y%m%dT%H%M%SZ).log"

echo "Capturing Apple-auth diagnostics for $BUNDLE_ID to $OUT_FILE"
echo "Reproduce the popup once, then press Ctrl-C."

# System prompts are owned by Apple daemons rather than the game process, so
# retain only the services that can request its Apple Account.  Redact obvious
# credentials, StoreKit cache-account tokens, device GUIDs, and e-mail addresses
# before the log reaches disk.
idevicesyslog -u "$UDID" 2>&1 |
    grep --line-buffered -Eia \
        'com\.awesomepiece\.castle|GameKit|Game Center|gamecenter|gamed|CloudKit|iCloud|StoreKit|appstored|itunesstored|AppleID|AuthenticationServices|accountsd|akd|identityservicesd' |
    sed -E \
        -e 's/[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}/<redacted-email>/g' \
        -e 's/[Bb]earer[[:space:]]+[^[:space:],;]+/Bearer <redacted>/g' \
        -e 's/([Aa]ccess[Tt]oken|[Aa]uthorization|[Pp]assword|[Ss]ession|[Tt]oken|[Gg][Uu][Ii][Dd])([[:space:]]*[:=][[:space:]]*)("[^"]+"|[^ ,;]+)/\1\2<redacted>/g' |
    tee "$OUT_FILE"
