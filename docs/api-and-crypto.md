# API & Crypto — talk to the server manually

The game API is encrypted, but the scheme is simple enough to script — useful for testing a handler
without the client.

## Cipher

- **AES-128-ECB**, key `b53019bb76da6b34` (16 ASCII bytes). Used for both request bodies and responses.
- **Padding**: the server pads the plaintext JSON with **trailing spaces** to a 16-byte multiple, then
  decodes the first JSON object and ignores trailing pad bytes (Newtonsoft tolerates trailing spaces,
  not other bytes). Requests may arrive as raw ciphertext **or** ASCII-hex of the ciphertext — hence the
  header name `encryptedWithHex`.
- Response header: `encryptedWithHex: true`, body = raw AES-ECB ciphertext.
- Auth header on real requests: `accesstoken: <token>` (NOT `Authorization: Bearer`). Time header =
  `MD5(unix_timestamp)`. For local testing against your own server these are not enforced.

## Encrypt a request / decrypt a response (python)

```python
from Crypto.Cipher import AES
import json, urllib.request

KEY = b"b53019bb76da6b34"

def enc(d: dict) -> bytes:
    raw = json.dumps(d).encode()
    if len(raw) % 16:
        raw += b" " * (16 - len(raw) % 16)      # space-pad
    return AES.new(KEY, AES.MODE_ECB).encrypt(raw)

def dec(b: bytes) -> dict:
    pt = AES.new(KEY, AES.MODE_ECB).decrypt(b)
    pt = pt[: pt.rindex(b"}") + 1]              # drop trailing pad
    return json.loads(pt.decode("utf-8", "ignore"))

# example: equip a skin and read the result
body = enc({"unit": 10000, "skin": 1000001})
req = urllib.request.Request(
    "http://127.0.0.1:8080/card/equipSkin", data=body,
    headers={"Content-Type": "application/json", "encryptedWithHex": "true"}, method="POST")
print(dec(urllib.request.urlopen(req).read()))
```

`curl` a GET the same way — the response is ciphertext, pipe it through `dec()`:

```bash
curl -s http://127.0.0.1:8080/treasure -o /tmp/r.bin      # then decrypt /tmp/r.bin with dec()
```

## Boot / login flow (what the client does)

```
POST /auth/shake-hand            handshake
POST /auth/checkPatchVersion     {version} -> ok
GET  /auth/getPatchFolder        -> {patchFolder}
GET  /auth/xcdSeed               XIGNCODE3 seed
GET  /auth/xcd?cookie=…          anti-cheat validate
POST /auth/register | /login     -> AuthResponseModel {accessToken, seed, serverTime, ...}
GET  /player                     -> PlayerDataResponseModel
GET  /player/currencies, /card/all, /deck, /treasure, /shop, ... (~280 more)
```

Success responses need `code: 0` and all model fields at typed defaults so Newtonsoft deserializes
without crashing. `server.py` fills the important screens from `state/*.json`; everything else returns a
wire-valid empty model. XIGNCODE3 is client-side anti-cheat — the server only answers the seed
handshake, a stub seed is enough for the API.

## Handler registration order

Direct `@app.get/post` handlers (e.g. `/pvp/info`) must register **before** the
`for _r in ROUTE_MODELS` loop to win. Lobby responses can also be filled via `OVERRIDES` (raw dict,
bypasses `build_model`). Unknown paths log `[UNKNOWN PATH]` and return a generic model. Full RVA/model
map: [../AGENTS.md](../AGENTS.md); datamine reference: [../KNOWLEDGE.md](../KNOWLEDGE.md).
