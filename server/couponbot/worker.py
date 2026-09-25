"""One worker cycle: read new codes from Discord, redeem them for every account.

    python3 -m couponbot.worker            # normal cycle (locked)
    python3 -m couponbot.worker --code XYZ # also force one code through
    python3 -m couponbot.worker --dry      # read + report, redeem nothing

Idempotent by construction: `redemptions` only ever gains rows, and a pair is
attempted once - see state.py for why (the site's "invalid or has already been
used" cannot be told apart from a wrong code).
"""

from __future__ import annotations

import argparse
import fcntl
import os
import sys
import time

from . import config, discord_feed, state
from .codes import extract
from .coupon_client import Limiter, Result, make_client, redeem, should_stop

# Consecutive transport failures worth abandoning a cycle for.
_MAX_ERRORS = 10


class _Lock:
    """Exclusive cycle lock: the dashboard's "run now" button and the timer
    must not redeem the same pair concurrently - the loser would burn a
    request, or record a worse result for an already-finished pair."""

    def __init__(self, blocking: bool = False):
        path = state.lock_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._fh = open(path, "a+")
        try:
            flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(self._fh, flags)
            self.acquired = True
        except OSError:
            self.acquired = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            if self.acquired:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
        finally:
            self._fh.close()

    def __bool__(self):
        return self.acquired


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __bool__(self):
        return True


def _notify(text: str) -> None:
    token = config.bot_token()
    channel = config.get("COUPON_NOTIFY_CHANNEL")
    if token and channel:
        discord_feed.send_message(token, channel, text)


def _pull_codes(summary: dict) -> None:
    """Discord -> `codes`. Never raises: a blocked token degrades to manual."""
    token = config.bot_token()
    channel = config.read_channel()
    if not token or not channel:
        state.meta_set("discord_mode", "manual")
        summary["discord"] = "not-configured"
        return

    cursor = state.meta_get("discord_cursor") or None
    prev_mode = state.meta_get("discord_mode") or "poll"
    try:
        messages = discord_feed.fetch_new_messages(token, channel, cursor)
        state.meta_set("discord_mode", "poll")
        summary["discord"] = f"poll:{len(messages)}"
    except discord_feed.DiscordError as exc:
        state.meta_set("discord_mode", "manual")
        summary["discord"] = f"manual:{exc}"
        if prev_mode != "manual":
            _notify("⚠️ **Coupon reader paused** (" + str(exc) + ") - add codes by "
                    "hand on the coupon dashboard until this clears.")
        return

    found: list[str] = []
    for msg in messages:
        text = discord_feed.message_text(msg)
        for code in extract(text):
            if state.add_code(code, f"discord:{msg['id']}", text):
                found.append(code)
        state.meta_set("discord_cursor", str(msg["id"]))
    summary["found"] = found
    summary["new_codes"] = len(found)


def _redeem_all(summary: dict, *, dry: bool = False) -> None:
    accs = state.accounts(enabled_only=True)
    if not accs:
        summary["note"] = "no accounts configured"
        return

    limiter = Limiter()
    client = make_client()
    errors = 0
    try:
        for code_row in state.open_codes():
            code = code_row["code"]
            for acc in accs:
                uid = acc["uid"]
                if not state.needs_attempt(uid, code):
                    continue
                if should_stop():
                    summary["stopped"] = "rate limit nearly exhausted"
                    return
                if errors >= _MAX_ERRORS:
                    summary["stopped"] = f"{errors} consecutive transport errors"
                    return
                if dry:
                    summary.setdefault("would_try", []).append((uid, code))
                    continue

                out = redeem(uid, code, client=client, limiter=limiter)
                summary["attempted"] += 1
                if out.result is Result.ERROR:
                    # Transport / unrecognised page: not recorded, so the pair
                    # is retried on the next cycle.
                    errors += 1
                    summary["errors"] += 1
                    continue
                errors = 0
                state.record_redemption(uid, code, out.result.value, out.message)
                if out.result is Result.OK:
                    summary["ok"] += 1
                elif out.result is Result.NO_COUPON:
                    # The code itself is unknown - a global fact, so stop.
                    state.set_code_status(code, "invalid")
                    break
                elif out.result is Result.EXPIRED:
                    state.set_code_status(code, "expired")
                    break
    finally:
        client.close()


def run_cycle(*, dry: bool = False, extra_code: str | None = None,
              lock: bool = True) -> dict:
    summary: dict = {"attempted": 0, "ok": 0, "errors": 0, "new_codes": 0,
                     "ts": time.time(), "dry": dry}
    ctx = _Lock(blocking=False) if lock else _NoLock()
    with ctx as lk:
        if not lk:
            summary["busy"] = True
            return summary
        state.init_db()
        run_id = None if dry else state.start_run()
        _pull_codes(summary)
        if extra_code:
            state.add_code(extra_code, "manual")
        _redeem_all(summary, dry=dry)
        if run_id is not None:
            state.finish_run(
                run_id,
                found=len(summary.get("found", [])),
                new=summary.get("new_codes", 0),
                attempted=summary["attempted"],
                ok=summary["ok"],
                failed=summary["errors"],
            )
        if not dry:
            _report(summary)
        return summary


def _report(summary: dict) -> None:
    """One Discord message per cycle, and only when something happened."""
    if summary.get("busy"):
        return
    parts = []
    if summary.get("new_codes"):
        parts.append("new code(s): " + ", ".join(summary["found"]))
    if summary.get("ok"):
        parts.append(f"redeemed for {summary['ok']}/{summary['attempted']} account(s)")
    if summary.get("errors"):
        parts.append(f"{summary['errors']} error(s)")
    if summary.get("stopped"):
        parts.append(f"stopped: {summary['stopped']}")
    if not parts:
        return
    mode = state.meta_get("discord_mode") or "?"
    _notify(f"🎟️ **Coupon run**: {'; '.join(parts)} (source: {mode})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="KGC coupon auto-redeem cycle")
    # `--once` is the default (and only) mode: one locked cycle per invocation.
    # It exists so the systemd unit documents what it does at a glance.
    ap.add_argument("--once", action="store_true",
                    help="run exactly one cycle (default)")
    ap.add_argument("--code", help="also add and try this code now")
    ap.add_argument("--dry", action="store_true", help="read/report only")
    ap.add_argument("--no-lock", action="store_true", help="ignore the cycle lock")
    args = ap.parse_args(argv)

    summary = run_cycle(dry=args.dry, extra_code=args.code, lock=not args.no_lock)
    print(summary)
    return 0 if not summary.get("errors") else 1


if __name__ == "__main__":
    sys.exit(main())
