"""Read (and post to) Discord with the shared bot token.

Read side is a plain REST poll - no gateway, no persistent connection - because
the worker only runs for a few seconds every cycle:

    GET /channels/{id}/messages?after={snowflake}&limit=50

The channel is one of OUR guild's channels (the official KingGodCastle
announcement channel is mirrored into it via Discord's "Follow Announcement
Channel" feature - see plans/coupon-autoredeem/02-discord.md). A bot cannot
read a guild it is not a member of: `403 Missing Access`, verified live.
"""

from __future__ import annotations

import time
from typing import Iterable

import httpx

API = "https://discord.com/api/v10"
TIMEOUT = 20.0


class DiscordError(Exception):
    """Base class - the worker decides whether to fall back to manual mode."""


class AuthError(DiscordError):
    """401: token revoked/rotated."""


class BlockedError(DiscordError):
    """403/429 we must not keep hammering (captcha challenge, hard block)."""


class MissingAccess(DiscordError):
    """403 code 50001: channel deleted or the bot lost read permission."""


def _auth(token: str) -> dict:
    # Bot tokens are sent bare with a `Bot ` prefix; never `Bearer`.
    return {"Authorization": f"Bot {token}"}


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 401:
        raise AuthError("discord token rejected (401)")
    if resp.status_code == 429:
        retry = resp.headers.get("Retry-After") or "60"
        raise BlockedError(f"discord rate limited, retry after {retry}s")
    if resp.status_code == 403:
        try:
            code = resp.json().get("code")
        except Exception:
            code = None
        if code == 50001:
            raise MissingAccess("missing access to channel")
        raise BlockedError(f"discord 403: {resp.text[:200]}")
    if resp.status_code == 404:
        raise MissingAccess("channel not found (404)")
    if resp.status_code >= 400:
        raise DiscordError(f"discord HTTP {resp.status_code}: {resp.text[:200]}")


def message_text(msg: dict) -> str:
    """Content plus any embed text - codes are posted either way."""
    parts = [msg.get("content") or ""]
    for emb in msg.get("embeds") or []:
        if emb.get("description"):
            parts.append(emb["description"])
        for field in emb.get("fields") or []:
            parts.append(field.get("value") or "")
        if emb.get("title"):
            parts.append(emb["title"])
    return "\n".join(p for p in parts if p)


def fetch_new_messages(token: str, channel_id: str, cursor: str | None = None,
                       *, limit: int = 50, max_pages: int = 5,
                       client: httpx.Client | None = None) -> list[dict]:
    """Messages after `cursor`, oldest first. `cursor=None` -> latest page."""
    if not token:
        raise AuthError("no discord token configured")
    if not channel_id:
        raise MissingAccess("no discord channel configured")

    own = client is None
    if own:
        client = httpx.Client(timeout=TIMEOUT, headers=_auth(token))
    out: list[dict] = []
    try:
        after = cursor
        for _ in range(max_pages):
            params: dict = {"limit": limit}
            if after:
                params["after"] = after
            resp = client.get(f"{API}/channels/{channel_id}/messages", params=params)
            _raise_for_status(resp)
            batch = resp.json()
            if not isinstance(batch, list) or not batch:
                break
            # `after` results come newest-last already; sort defensively.
            batch.sort(key=lambda m: int(m["id"]))
            out.extend(batch)
            after = batch[-1]["id"]
            if len(batch) < limit:
                break
            time.sleep(0.4)
    finally:
        if own:
            client.close()
    return out


def send_message(token: str, channel_id: str, content: str, *,
                 client: httpx.Client | None = None) -> str | None:
    if not token or not channel_id:
        return None
    own = client is None
    if own:
        client = httpx.Client(timeout=TIMEOUT, headers=_auth(token))
    try:
        resp = client.post(f"{API}/channels/{channel_id}/messages",
                           json={"content": content[:1900]})
        if resp.status_code >= 400:
            return None
        return resp.json().get("id")
    except httpx.HTTPError:
        return None
    finally:
        if own:
            client.close()
