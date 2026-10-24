"""api/config.py must stay in sync with what the game client actually sends.

Two real bugs this pins, both found 2026-10-09 by tools/prod_probe.py against
prod (see docs/dev-notes.md §33):
  - a stale AES key (the v169 value) makes prod answer HTTP 400 to every POST,
    and leaves responses undecryptable;
  - `platform` is a client header (Web.<Get>d__14 / <Post>d__17) and its absence
    changed no token verdict, but it is part of the wire format.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _key(path: Path):
    m = re.search(r'AES_KEY\s*=\s*b"([0-9a-f]{16})"', path.read_text())
    return m.group(1) if m else None


def test_api_and_server_share_the_game_aes_key():
    # Same key in both trees: the client encrypts once, both decoders must agree.
    assert _key(ROOT / "api" / "config.py") == _key(ROOT / "server" / "crypto.py")


def test_request_headers_match_the_client():
    sys.path.insert(0, str(ROOT))
    import api.config as cfg

    h = cfg.SESSION.headers
    assert h["version"]
    assert h["platform"] in ("IPhonePlayer", "Android")
    # time = AES-ECB(str(unix_ms)) -> one 16-byte block -> 32 hex chars.
    # md5 of unix seconds is also 32 chars, so pin the shape plus the AES diff.
    assert re.fullmatch(r"[0-9a-f]{32}", cfg._time_header())
    # encrypt -> decrypt round trip pins the zero padding both ends rely on
    assert cfg.aes_decrypt(cfg.aes_encrypt('{"a":1}')) == b'{"a":1}'
    # Headers the client never sends (dev-notes §31).
    assert "encryptedwithhex" not in h
    assert "x-unity-version" not in h
