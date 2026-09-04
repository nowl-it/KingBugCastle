"""
Replay guest login against the OFFICIAL KGC API using a known loginId.

The client's own flow is GET /auth?id=<loginId>&cookie=<gpgs-cookie>&platform=Android
(RestAPI.Auth) - no password, no anti-cheat payload in the request itself. The
loginId is a bearer credential minted at first launch (RegisterRequestModel).

Usage:
    python3 api/auth/replay_login.py <loginId> [--save]

On success writes captured_token.txt (+ captured_guest.json) so config._autoload_token()
and api/ranking/fetch_seasonal.py pick the token up automatically.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from api.config import SESSION, VERSION, decode_response, get  # noqa: E402


def auth(login_id: str, cookie: str = "", platform: str = "Android") -> dict:
    params = {"id": login_id}
    if cookie:
        params["cookie"] = cookie
    if platform:
        params["platform"] = platform
    import time as _time
    import hashlib
    r = SESSION.get(
        "https://kgc-k8s-1.awesomepiece.com/auth",
        params=params,
        headers={"time": hashlib.md5(str(int(_time.time())).encode()).hexdigest()},
        timeout=15,
    )
    print(f"HTTP {r.status_code} {r.url}")
    return decode_response(r.content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("login_id")
    ap.add_argument("--cookie", default="")
    ap.add_argument("--platform", default="Android")
    ap.add_argument("--save", action="store_true", help="persist token to captured_token.txt")
    args = ap.parse_args()

    resp = auth(args.login_id, args.cookie, args.platform)
    print(json.dumps(resp, indent=2, ensure_ascii=False)[:2000])

    if isinstance(resp, dict) and resp.get("accessToken"):
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        if args.save:
            with open(os.path.join(root, "captured_token.txt"), "w") as f:
                f.write(resp["accessToken"])
            with open(os.path.join(root, "captured_guest.json"), "w") as f:
                json.dump({"loginId": args.login_id,
                           "expiredAt": resp.get("expiredAt"),
                           "serverTime": resp.get("serverTime"),
                           "seed": resp.get("seed")}, f, indent=2)
        print(f"\nOK accessToken={resp['accessToken'][:24]}... (expiredAt={resp.get('expiredAt')})")
        return 0
    print("\nFAIL: no accessToken in response")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
