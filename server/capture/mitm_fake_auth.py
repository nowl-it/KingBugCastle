"""
mitmproxy addon: make the modified KGC build pass guest login by returning
properly-encrypted SUCCESS auth responses (bypassing the server-side integrity
check that rejects tampered builds with code 410). Everything else passes
through to the real servers.

KGC API crypto: AES-128-ECB, PKCS7, key 'b53019bb76da6b34', body = raw ciphertext,
response header encryptedWithHex: true. Responses need code:200 + success:true.

  mitmdump --listen-host 0.0.0.0 --listen-port 8888 -w /tmp/kgc.flows -s server/mitm_fake_auth.py
"""
import json, secrets, datetime
from mitmproxy import http
from Crypto.Cipher import AES

KEY = b'b53019bb76da6b34'

def now(d=0):
    return (datetime.datetime.utcnow()+datetime.timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def _pad(b):
    p = 16 - len(b) % 16
    return b + bytes([p])*p

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

def request(flow: http.HTTPFlow):
    if "kgc-k8s-1.awesomepiece.com" not in flow.request.pretty_host:
        return
    path = flow.request.path.split("?")[0]
    q = flow.request.query
    gid = q.get("id", "Guest_DEV")

    if path == "/auth":
        # the integrity gate: real server returns {"code":410,"msg":"Fail"} for tampered builds.
        flow.response = enc_resp(auth_ok(gid))
        print(f"[FAKE] /auth id={gid} -> success(200)")
    elif path == "/auth/login":
        # after /auth returns accessToken, client POSTs /auth/login(token); real server 401s our token.
        flow.response = enc_resp(auth_ok(gid))
        print(f"[FAKE] /auth/login -> success(200)")
    elif path == "/auth/register":
        flow.response = enc_resp({"code": 200, "msg": None, "success": True,
                                  "accessToken": None, "expiredAt": None, "seed": None,
                                  "serverTime": None, "blockedUntilAt": None,
                                  "blockedComment": None, "loginId": gid})
        print(f"[FAKE] /auth/register -> ok loginId={gid}")
    elif path == "/auth/xcdSeed":
        flow.response = enc_resp({"code": 200, "msg": None, "success": True,
                                  "accessToken": None, "expiredAt": None,
                                  "seed": secrets.token_hex(64), "serverTime": now(0),
                                  "blockedUntilAt": None, "blockedComment": None})
        print(f"[FAKE] /auth/xcdSeed -> ok")
    # else: pass through (illust, usePatch, getPatchFolder, CDN)
