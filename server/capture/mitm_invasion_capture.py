"""
mitmproxy addon: capture the REAL client's live requests against the REAL
backend while playing - specifically to see what the client actually sends
when tapping Invasion I-1 (root-causing the always-theme:1 bug).

Reuses mitm_fake_auth's integrity-gate bypass (real server 410s modified
builds at /auth) so the patched client can log in, then decrypts and prints
every request/response body for the paths we care about. Everything else
passes through untouched.

  mitmdump --listen-host 0.0.0.0 --listen-port 8888 \
    -w /tmp/kgc_invasion.flows -s server/capture/mitm_invasion_capture.py
"""
import json, secrets, datetime
from mitmproxy import http
from Crypto.Cipher import AES

KEY = b'b53019bb76da6b34'
WATCH_SUBSTR = ("game/start", "invasion", "theme", "player")


def now(d=0):
    return (datetime.datetime.utcnow() + datetime.timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _pad(b):
    # Real server convention is zero-byte padding (see api/config.py aes_decrypt,
    # which rstrip(b"\x00")s) - NOT PKCS7. Using PKCS7 here left pad-length
    # marker bytes in the decrypted plaintext that the client's strict
    # JsonConvert.DeserializeObject(checkAdditionalContent=true) rejected.
    p = 16 - len(b) % 16
    if p == 16:
        return b
    return b + bytes(p)


def enc_resp(obj):
    ct = AES.new(KEY, AES.MODE_ECB).encrypt(_pad(json.dumps(obj).encode()))
    return http.Response.make(200, ct, {
        "Content-Type": "application/json",
        "version": "170.0.03",
        "encryptedWithHex": "true",
    })


def auth_ok(login_id):
    return {
        "code": 200, "msg": None, "success": True,
        "accessToken": "DEV" + secrets.token_hex(20),
        "expiredAt": now(30), "seed": secrets.token_hex(8),
        "serverTime": now(0), "blockedUntilAt": None,
        "blockedComment": None, "loginId": login_id,
    }


def try_decrypt(raw: bytes):
    if not raw or len(raw) % 16 != 0:
        return None
    try:
        dec = AES.new(KEY, AES.MODE_ECB).decrypt(raw).rstrip(b"\x00")
        return json.loads(dec)
    except Exception:
        try:
            return dec.decode("utf-8", "replace")
        except Exception:
            return None


def watched(path: str) -> bool:
    return any(s in path for s in WATCH_SUBSTR)


def request(flow: http.HTTPFlow):
    if "awesomepiece.com" not in flow.request.pretty_host:
        return
    path = flow.request.path.split("?")[0]
    q = flow.request.query
    gid = q.get("id", "Guest_DEV")

    if path == "/auth":
        flow.response = enc_resp(auth_ok(gid))
        print(f"[FAKE] /auth id={gid} -> success(200)")
        return
    elif path == "/auth/login":
        flow.response = enc_resp(auth_ok(gid))
        print(f"[FAKE] /auth/login -> success(200)")
        return
    elif path == "/auth/register":
        flow.response = enc_resp({"code": 200, "msg": None, "success": True,
                                   "accessToken": None, "expiredAt": None, "seed": None,
                                   "serverTime": None, "blockedUntilAt": None,
                                   "blockedComment": None, "loginId": gid})
        print(f"[FAKE] /auth/register -> ok loginId={gid}")
        return
    elif path == "/auth/xcdSeed":
        flow.response = enc_resp({"code": 200, "msg": None, "success": True,
                                   "accessToken": None, "expiredAt": None,
                                   "seed": secrets.token_hex(64), "serverTime": now(0),
                                   "blockedUntilAt": None, "blockedComment": None})
        print(f"[FAKE] /auth/xcdSeed -> ok")
        return

    if watched(path):
        body = try_decrypt(flow.request.content)
        print(f"\n>>> REQUEST {flow.request.method} {path}")
        print(json.dumps(body, indent=2, ensure_ascii=False) if body is not None else f"  <undecryptable, {len(flow.request.content)} bytes>")


def response(flow: http.HTTPFlow):
    if "awesomepiece.com" not in flow.request.pretty_host:
        return
    path = flow.request.path.split("?")[0]
    if watched(path):
        body = try_decrypt(flow.response.content)
        print(f"<<< RESPONSE {path}")
        print(json.dumps(body, indent=2, ensure_ascii=False) if body is not None else f"  <undecryptable, {len(flow.response.content)} bytes>")
