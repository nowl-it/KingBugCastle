# Auth APIs

Base URL: `https://kgc-k8s-1.awesomepiece.com`

## Encryption

- AES-128-ECB, zero padding, hex output
- Key v169.0.03: `b53019bb76da6b34` (v165-168: `cnf1tl65djs2wp3g`)
- POST body: raw hex string, `Content-Type: application/json`
- Auth header: `accesstoken: <token>` (not `Authorization: Bearer`)
- Response: raw binary AES-ECB → msgpack or JSON

---

## Real Auth Flow (confirmed from MITM captures)

```
1. GET  /auth/xcdSeed                      # get seed, no auth
2. [client-side] generate Xigncode cookie with seed (anti-cheat SDK)
3. GET  /auth/xcd?cookie=<xcd_cookie>      # device registration, no auth
4. POST /auth/login                        # with accesstoken header set
5. POST /auth/shake-hand                   # heartbeat every ~60s
```

Getting `accessToken`:
- Stored on device after first registration
- Refreshed via `/auth/xcd` Xigncode validation each session
- **Cannot be bypassed without Xigncode SDK or game binary**

---

## Endpoints

### GET /auth/xcdSeed

No auth required.

Response (`AuthResponseModel`):
```json
{
  "seed": "<long_random_string>",
  "accessToken": null,
  "success": true
}
```

### GET /auth/xcd?cookie=\<xigncode_cookie\>

No auth required. Validates Xigncode anti-cheat cookie.

Cookie format: `926988XXXX_<md5_device_fingerprint>_<md5_checksum>`

Response: `AuthResponseModel` (accessToken may be null if device already registered)

### POST /auth/login

Requires `accesstoken` header.

Request body (`LoginRequestModel` - confirmed from MITM):
```json
{
  "locale": "VI",
  "platform": "IPhonePlayer",
  "deviceInfo": "iPhone13,3",
  "version": "169.0.03",
  "cookie": "<xigncode_cookie>"
}
```

Known platform values: `IPhonePlayer`, `Android`

Response: `AuthResponseModel` (accessToken: null - token already stored on device)

### POST /auth/register

Requires `accesstoken` header (from xcd step).

Request body (`RegisterRequestModel` - from IL2CPP dump.cs):
```json
{
  "type": 0,
  "id": "<xigncode_cookie>",
  "userName": "KingName",
  "castleName": "CastleName",
  "kingPostfix": 0,
  "castlePostfix": 0,
  "version": 169003
}
```

- `id`: Xigncode cookie from `/auth/xcd` (NOT device UUID)
- `kingPostfix` / `castlePostfix`: numeric suffix shown after name
- Errors: `WrongKingName` (invalid id or name), `NameNotVerified` (no version field)

### POST /auth/shake-hand

Heartbeat. No body needed. Send every ~60s.

### GET /auth?id=\<device_id\>&version=169003

Check if device exists.

Response: `{ "code": 404, "msg": "...", "success": false }` if new device.

### GET /auth/checkPatchVersion?version=\<version\>

Returns 403 if patch is outdated.

### POST /auth/getPatchFolder

Returns CDN folder path for patch download.

### GET /auth/usePatch?platform=\<platform\>

Confirm patch applied. Platforms: `IPhonePlayer`, `Android`

---

## Account Transfer

### GET /auth/transfer/code

Returns transfer code (use on old device).

### POST /auth/transfer

```json
{ "code": "TRANSFER_CODE", "type": 0 }
```

### POST /auth/link

Link guest account to platform.
```json
{ "code": "AUTH_CODE", "type": 2 }
```
- `type`: 2=Google, 3=Apple

---

## Quick Start (when you have a fresh Xigncode cookie from MITM)

```python
from auth.auth import set_session_token, login, full_auth_flow

# Option A: already have cookie from MITM capture
xigncode_cookie = "926988XXXX_<fingerprint>_<checksum>"
login_resp = full_auth_flow(xigncode_cookie)

# Option B: manually set token captured from traffic
set_session_token("gw3a0ahYX-Bc8JaWFGdkQ_UPOQoo1w4R")
# then call any API directly
```
