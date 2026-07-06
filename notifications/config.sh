#!/usr/bin/env bash
# KGC Notification System - Shared Configuration
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NOTI_DIR="$PROJECT_DIR/notifications"

NTFY_SERVER="https://ntfy.sh"
TOPIC_PREFIX="nowl"
SUMMARY_TOPIC="nowl-summary"

LANGUAGES=(en zh ja vi th de es fr pt it ru ar id pl tr)

STATE_DIR="$HOME/.local/share/kgc_notifications"
mkdir -p "$STATE_DIR"

# Optional ntfy auth token (Authorization: Bearer). Empty = public topic.
NTFY_TOKEN="${NTFY_TOKEN:-}"
