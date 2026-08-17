"""AES wire crypto for the KGC client.

The game encrypts every API payload with AES-128-ECB. Two quirks make this
worth a module of its own:

- Responses are space-padded (NOT PKCS7): the client's Newtonsoft JSON reader
  throws "Additional text after JSON" on non-whitespace trailing bytes, but
  tolerates trailing spaces.
- Requests arrive either as raw binary or as ASCII hex text of the ciphertext
  (matches the "encryptedWithHex" header literally). Endpoints with meaningful
  POST bodies need this; GET-only / body-ignoring endpoints never exposed it.
"""
import json

from Crypto.Cipher import AES

AES_KEY = b"b53019bb76da6b34"


def aes_encrypt(payload: dict) -> bytes:
    # Space-pad to 16-byte blocks (NOT PKCS7): see module docstring.
    raw = json.dumps(payload).encode()
    if len(raw) % 16:
        raw += b" " * (16 - len(raw) % 16)
    return AES.new(AES_KEY, AES.MODE_ECB).encrypt(raw)


def encrypted_response(payload: dict) -> "Response":
    """Standard AES-encrypted JSON response the game client expects."""
    from fastapi.responses import Response
    return Response(aes_encrypt(payload), media_type="application/json",
                    headers={"encryptedWithHex": "true"})


def aes_decrypt(data: bytes) -> dict:
    # Some request bodies (e.g. /deck/set) arrive as ASCII hex text of the
    # ciphertext, not raw binary - matches the "encryptedWithHex" header name
    # literally. Endpoints with meaningful POST bodies need this; GET-only /
    # body-ignoring endpoints never exposed the bug. Detect and unwrap first.
    if len(data) % 2 == 0 and all(c in b"0123456789abcdefABCDEF" for c in data):
        try:
            data = bytes.fromhex(data.decode("ascii"))
        except ValueError:
            pass
    # Tolerant of any padding scheme the client uses (PKCS7, space, or null):
    # decode the first JSON object and ignore trailing pad bytes.
    raw = AES.new(AES_KEY, AES.MODE_ECB).decrypt(data)
    text = raw.decode("utf-8", "ignore").lstrip()
    return json.JSONDecoder().raw_decode(text)[0]