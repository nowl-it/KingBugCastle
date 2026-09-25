"""Client for the official coupon site: POST /submitCoupon -> parsed result.

The site is HTML-only (no JSON API), rate-limited (X-Rate-Limit-Remaining
starts at ~300) and has no captcha. `lang=en_us` is pinned so the response
words are always the English ones we match on - Phase 0 calibrated every
marker against the live site (see plans/coupon-autoredeem/00-recon.md):

    Success! / Rewards have been sent to your inbox. Please log in to check.
    This Player-ID does not exist. Please check and try again.
    This coupon does not exist.
    This coupon number is invalid or has already been used.
    This coupon has expired.
    The coupon cannot be entered currently. Please try again later.
    The usage limit has been reached.
    Failed to enter coupon (h1 on every failure)

Note the second and third lines are distinct: "coupon does not exist" means the
code itself is unknown (a global fact -> stop trying it on other accounts),
while "invalid or has already been used" is per-account and ambiguous - that is
why each (uid, code) pair is attempted exactly once.
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass
from enum import Enum

import httpx

SITE = "https://kgc-coupon.awesomepiece.com"
SUBMIT = "/submitCoupon"

DEFAULT_TIMEOUT = 20.0


class Result(str, Enum):
    OK = "ok"
    NO_PID = "no_pid"
    NO_COUPON = "no_coupon"
    USED_OR_INVALID = "used_or_invalid"
    EXPIRED = "expired"
    NOT_AVAILABLE = "not_available"
    LIMIT_REACHED = "limit_reached"
    ERROR = "error"

    @classmethod
    def coerce(cls, value) -> "Result":
        if isinstance(value, cls):
            return value
        return cls(value)


# (distinctive page text, result) - first match wins, so the more specific
# markers come first.
_MARKERS: tuple[tuple[str, Result], ...] = (
    ("rewards have been sent", Result.OK),
    ("success!", Result.OK),
    ("player-id does not exist", Result.NO_PID),
    ("this coupon does not exist", Result.NO_COUPON),
    ("invalid or has already been used", Result.USED_OR_INVALID),
    ("this coupon has expired", Result.EXPIRED),
    ("cannot be entered currently", Result.NOT_AVAILABLE),
    ("usage limit has been reached", Result.LIMIT_REACHED),
)

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


# Shared throttle/rate-limit view - the worker reads it to decide whether to
# stop a cycle early instead of burning the remaining quota on retries.
RATE = {"remaining": None, "blocked_until": 0.0}


def _text(fragment: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", fragment)).strip()


def parse_page(html: str) -> tuple[Result, str]:
    """Map a response page to (Result, message text). ERROR = unrecognised."""
    h1s = [_text(m) for m in re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)]
    ps = [_text(m) for m in re.findall(r"<p[^>]*>(.*?)</p>", html, re.S | re.I)]
    message = ps[0] if ps else (h1s[0] if h1s else "")
    haystack = " ".join(h1s + ps).lower()
    for marker, result in _MARKERS:
        if marker in haystack:
            return result, message
    return Result.ERROR, message


class Limiter:
    """Serialise requests: >= COUPON_MIN_INTERVAL seconds (+ jitter) apart."""

    def __init__(self, interval: float | None = None):
        if interval is None:
            interval = float(os.environ.get("COUPON_MIN_INTERVAL", "2.0"))
        self.interval = interval
        self._last = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            self._last = time.monotonic()
            return
        now = time.monotonic()
        delay = self._last + self.interval - now
        if delay > 0:
            time.sleep(delay + random.uniform(0.0, 0.5))
            now = time.monotonic()
        self._last = now


@dataclass
class Outcome:
    result: Result
    message: str
    http_status: int = 0
    remaining: int | None = None


def make_client() -> httpx.Client:
    return httpx.Client(
        base_url=SITE,
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
        },
    )


def should_stop() -> bool:
    """True when the site asked us to back off or the quota is nearly gone."""
    if time.time() < RATE["blocked_until"]:
        return True
    rem = RATE["remaining"]
    return rem is not None and rem <= 5


def redeem(uid: str, code: str, *, client: httpx.Client | None = None,
           limiter: Limiter | None = None, save_raw: bool = True) -> Outcome:
    """One attempt. Caller must guarantee the (uid, code) pair is new."""
    own_client = client is None
    if own_client:
        client = make_client()
    (limiter or Limiter()).wait()
    try:
        try:
            resp = client.post(
                SUBMIT,
                data={"uid": uid, "code": code, "lang": "en_us"},
            )
        except httpx.HTTPError as exc:
            return Outcome(Result.ERROR, f"network: {exc}")

        raw_remaining = resp.headers.get("X-Rate-Limit-Remaining")
        remaining = int(raw_remaining) if (raw_remaining or "").isdigit() else None
        RATE["remaining"] = remaining
        retry_after = resp.headers.get("Retry-After")
        if resp.status_code in (429, 503) or (retry_after or "").isdigit():
            RATE["blocked_until"] = time.time() + int(retry_after or 60)
        if resp.status_code != 200:
            return Outcome(Result.ERROR, f"HTTP {resp.status_code}",
                           resp.status_code, remaining)

        result, message = parse_page(resp.text)
        if result is Result.ERROR and save_raw:
            from . import state  # local import: keeps the module import-light
            state.save_raw(resp.text, uid, code)
        return Outcome(result, message, resp.status_code, remaining)
    finally:
        if own_client:
            client.close()
