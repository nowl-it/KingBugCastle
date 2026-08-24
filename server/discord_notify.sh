#!/usr/bin/env bash
# Send one message through the KGC Discord bot.  Keep the bot token out of git:
# put it in server/secrets/discord_bot_token (chmod 600) or set DISCORD_BOT_TOKEN.
set -euo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
    echo "usage: $0 <message>" >&2
    exit 2
fi

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOKEN_FILE="$ROOT_DIR/server/secrets/discord_bot_token"
TOKEN="${DISCORD_BOT_TOKEN:-}"
if [[ -z "$TOKEN" && -r "$TOKEN_FILE" ]]; then
    TOKEN="$(<"$TOKEN_FILE")"
fi

if [[ -z "$TOKEN" ]]; then
    echo "Discord notification skipped: missing bot token ($TOKEN_FILE)" >&2
    exit 1
fi

payload=$(python3 -c 'import json, sys; print(json.dumps({"content": sys.argv[1]}))' "$1")
response=$(curl --silent --show-error --fail-with-body \
    --request POST \
    --header "Authorization: Bot $TOKEN" \
    --header 'Content-Type: application/json' \
    --data "$payload" \
    'https://discord.com/api/v10/channels/1541439188686213221/messages')

echo "Discord notification sent: $(python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])' <<<"$response")"
