"""
KGC API - shared config, AES-ECB encrypt/decrypt, session helper
Base URL: https://kgc-k8s-1.awesomepiece.com

AES: ECB, Zeros padding, hex output, key = cnf1tl65djs2wp3g (AES-128)
POST body: raw hex string (Content-Type: application/json)
Auth header: accesstoken (not Authorization: Bearer)
"""

BASE_URL = "https://kgc-k8s-1.awesomepiece.com"
AES_KEY = b"b53019bb76da6b34"  # AES-128, v169.0.03 key (v165-168 used cnf1tl65djs2wp3g)

import hashlib
import json
import time as _time
import requests
import msgpack
from Crypto.Cipher import AES


def aes_encrypt(data: str) -> str:
    """Encrypt UTF-8 string -> hex string (AES-128-ECB, zero padding)."""
    raw = data.encode("utf-8")
    pad_len = 16 - (len(raw) % 16)
    if pad_len == 16:
        pad_len = 0
    raw = raw + b"\x00" * pad_len
    return AES.new(AES_KEY, AES.MODE_ECB).encrypt(raw).hex()


def aes_decrypt(hex_str: str) -> bytes:
    """Decrypt hex string -> raw bytes (AES-128-ECB), strip zero padding."""
    data = bytes.fromhex(hex_str.strip())
    return AES.new(AES_KEY, AES.MODE_ECB).decrypt(data).rstrip(b"\x00")


def _time_header() -> str:
    """Generate time header: MD5 of current unix timestamp as string."""
    ts = str(int(_time.time()))
    return hashlib.md5(ts.encode()).hexdigest()


def _try_decode(raw: bytes) -> dict | list | str | None:
    """Try msgpack then JSON on raw bytes."""
    stripped = raw.rstrip(b"\x00")
    try:
        return msgpack.unpackb(stripped, raw=False)
    except Exception:
        pass
    try:
        return json.loads(stripped.decode("utf-8", errors="replace"))
    except Exception:
        pass
    return None


def decode_response(content: bytes) -> dict | list | str:
    """
    Decode server response:
    1. raw binary length % 16 == 0 -> AES ECB decrypt -> msgpack/JSON
    2. text hex -> AES decrypt -> msgpack/JSON
    3. plain JSON
    4. raw bytes hex
    """
    # 1. Raw binary AES (server always sends binary)
    if len(content) >= 16 and len(content) % 16 == 0:
        try:
            decrypted = AES.new(AES_KEY, AES.MODE_ECB).decrypt(content).rstrip(b"\x00")
            result = _try_decode(decrypted)
            if result is not None:
                return result
        except Exception:
            pass

    # 2. Hex-encoded AES (fallback)
    text = content.decode("utf-8", errors="replace").strip()
    if len(text) % 2 == 0 and len(text) >= 32:
        try:
            decrypted = aes_decrypt(text)
            result = _try_decode(decrypted)
            if result is not None:
                return result
        except Exception:
            pass

    # 3. Plain JSON
    try:
        return json.loads(content)
    except Exception:
        pass

    return content.decode("utf-8", errors="replace")


# Client version. Server WAF returns 403 for stale version headers (e.g. 169.0.03).
VERSION = "169.1.05"

SESSION: requests.Session = requests.Session()
SESSION.headers.update({
    "version": VERSION,
    "x-unity-version": "2022.3.62f3",
    "encryptedwithhex": "true",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "vi-VN,vi;q=0.9",
    "User-Agent": f"ProductName/{VERSION}.0 CFNetwork/3860.300.31 Darwin/25.2.0",
})


def set_auth_token(token: str):
    """Set accesstoken header after login."""
    SESSION.headers.update({"accesstoken": token})


def _autoload_token():
    """Load accesstoken from KGC_TOKEN env or captured_token.txt (repo root)."""
    import os
    tok = os.environ.get("KGC_TOKEN", "").strip()
    if not tok:
        path = os.path.join(os.path.dirname(__file__), "..", "captured_token.txt")
        try:
            with open(path) as f:
                tok = f.read().strip()
        except OSError:
            tok = ""
    if tok:
        set_auth_token(tok)
    return tok


_autoload_token()


def _parse(r: requests.Response) -> dict | list | str:
    r.raise_for_status()
    return decode_response(r.content)


def _get_url(path: str) -> str:
    if path.startswith("/ranking"):
        return "https://kgc-ranking-1.awesomepiece.com" + path
    return BASE_URL + path


def get(path: str, params: dict = None):
    r = SESSION.get(
        _get_url(path),
        params=params,
        headers={"time": _time_header()},
        timeout=15,
    )
    return _parse(r)


def post(path: str, body: dict = None):
    """POST with AES-encrypted hex body."""
    payload = aes_encrypt(json.dumps(body or {}, separators=(",", ":")))
    r = SESSION.post(
        _get_url(path),
        data=payload,
        headers={"time": _time_header()},
        timeout=15,
    )
    return _parse(r)


def put(path: str, body: dict = None):
    payload = aes_encrypt(json.dumps(body or {}, separators=(",", ":")))
    r = SESSION.put(
        _get_url(path),
        data=payload,
        headers={"time": _time_header()},
        timeout=15,
    )
    return _parse(r)


def delete(path: str):
    r = SESSION.delete(
        _get_url(path),
        headers={"time": _time_header()},
        timeout=15,
    )
    return _parse(r)
