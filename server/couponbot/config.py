"""Runtime configuration for the coupon bot.

Precedence: process environment > `server/secrets/coupon.env` (operator-owned,
gitignored like every other secret in this repo) > sensible defaults.

Nothing here is a secret value itself - secrets live in `server/secrets/` and
are read lazily by the helpers below so tests never touch them.
"""

from __future__ import annotations

import os
import pathlib

_SERVER = pathlib.Path(__file__).resolve().parent.parent
SECRETS = _SERVER / "secrets"
ENV_FILE = SECRETS / "coupon.env"

_LOADED = False

DEFAULTS = {
    # Where the bot reads codes: the channel in OUR guild that mirrors the
    # official KingGodCastle announcement channel (Discord "Follow").
    "COUPON_DISCORD_CHANNEL": "",
    # Where the bot posts its own run summaries (same channel the CDN monitor
    # already uses). Empty disables notifications.
    "COUPON_NOTIFY_CHANNEL": "1541439188686213221",
    "COUPON_WEB_PORT": "8083",
    "COUPON_MIN_INTERVAL": "2.0",
    "COUPON_LANG": "en_us",
}


def _load_env_file() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def get(key: str, default: str | None = None) -> str:
    _load_env_file()
    if key in os.environ and os.environ[key] != "":
        return os.environ[key]
    if default is not None:
        return default
    return DEFAULTS.get(key, "")


def bot_token() -> str:
    """Read the shared Discord bot token (the CDN monitor's own token)."""
    _load_env_file()
    token = os.environ.get("COUPON_DISCORD_TOKEN") or ""
    if token:
        return token
    path = SECRETS / "discord_bot_token"
    if path.is_file():
        return path.read_text().strip()
    return ""


def web_password() -> str:
    """Dashboard password. Empty means auth is disabled (local dev only)."""
    _load_env_file()
    return os.environ.get("COUPON_WEB_PASSWORD", "")


def web_secret() -> str:
    """HMAC key for the session cookie; auto-generated on first web start."""
    _load_env_file()
    secret = os.environ.get("COUPON_WEB_SECRET", "")
    if secret:
        return secret
    path = SECRETS / "coupon_web_secret"
    if path.is_file():
        return path.read_text().strip()
    # Deterministic-enough per boot is wrong for a session cookie: persist it.
    import secrets as _secrets
    value = _secrets.token_hex(32)
    try:
        SECRETS.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n")
        path.chmod(0o600)
    except OSError:
        pass
    return value


def read_channel() -> str:
    return get("COUPON_DISCORD_CHANNEL")
