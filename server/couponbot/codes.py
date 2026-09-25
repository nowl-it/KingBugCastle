"""Coupon code extractor for Discord message text.

False positives cost a real HTTP request to the official site (and would litter
the store with codes that do not exist), so a candidate only counts when it
looks like a code *and* sits in a plausible context:

  * inside a code span/block (``` or `), or
  * on a line that mentions coupon/code/gift/쿠폰/코드 ...

and never on a line that carries a URL, never an md5/sha hex blob, never a
known non-code token (DISCORD..., HTTP...).
"""

from __future__ import annotations

import re

# Letters/digits plus an optional dash, >=8 alphanumerics, must mix a letter
# and a digit (pure words like "ANNOUNCEMENT" are never codes).
_CANDIDATE = re.compile(r"(?<![A-Z0-9])[A-Z0-9](?:[A-Z0-9-]{6,30})[A-Z0-9](?![A-Z0-9])")
_CONTEXT = re.compile(
    r"coupon|code|gift|redeem|present|프로모|쿠폰|코드|선물|쿠폰번호",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://|www\.|\S+\.(?:com|net|gg|io|xyz|kr|vn)\b", re.IGNORECASE)
_CODE_SPAN = re.compile(r"```(.*?)```|`([^`\n]+)`", re.DOTALL)
_HEX = re.compile(r"^[A-F0-9]+$")
_BLOCKLIST = ("DISCORD", "HTTP", "HTTPS", "WWW", "GITHUB", "YOUTUBE", "TWITCH",
              "PATREON", "KINGGOD", "AWESOMEPIECE")

_MAX_LEN, _MIN_LEN = 20, 8


def _plausible(token: str) -> bool:
    alnum = token.replace("-", "")
    if not (_MIN_LEN <= len(alnum) <= _MAX_LEN):
        return False
    if not (any(c.isdigit() for c in alnum) and any(c.isalpha() for c in alnum)):
        return False
    if _HEX.match(alnum) and len(alnum) in (32, 40, 64):
        return False  # md5 / sha1 / sha256
    if token.startswith(_BLOCKLIST):
        return False
    return True


def _tokens(text: str) -> list[str]:
    return [m.group(0) for m in _CANDIDATE.finditer(text.upper()) if _plausible(m.group(0))]


def extract(text: str) -> list[str]:
    """Ordered, de-duplicated candidate codes found in a message body."""
    if not text:
        return []
    text = text.replace("\u200b", "")
    upper = text.upper()
    found: list[str] = []
    seen: set[str] = set()

    def take(token: str) -> None:
        if token not in seen:
            seen.add(token)
            found.append(token)

    # 1. Code spans/blocks: the strongest signal, no context needed.
    for span in _CODE_SPAN.findall(upper):
        for part in span:
            for tok in _tokens(part):
                take(tok)

    # 2. Line-level: needs a coupon-ish word on the same line, and no URL.
    for line in upper.splitlines():
        if _URL.search(line):
            continue
        if not _CONTEXT.search(line):
            continue
        for tok in _tokens(line):
            take(tok)

    return found
