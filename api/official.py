#!/usr/bin/env python3
"""Call the official KGC API with a live session.

The ONLY scarce resource is a valid XIGNCODE cookie (time-windowed, minted by the
real client). Everything downstream is free and scriptable:

    cookie  --GET /auth/xcd-->  accesstoken + refreshtoken
    token   --POST /auth/login-->  loginId  (certifies the session)
    token   --GET  /auth/shake-hand-->  slides the session window (keep-alive)

So: capture ONE cookie (harvest.py), mint a token, then keep it alive forever with
shake-hand. No need to re-capture while shake-hand keeps answering 200.

Usage:
    python3 api/official.py --cookie "<cookie>"          # mint + demo + keep-alive
    python3 api/official.py --token  "<token>"           # reuse a live token
    python3 api/official.py --keepalive 60               # ping every 60s, forever
"""
import argparse
import sys
import time

sys.path.insert(0, "api")
import config
import auth

OFFICIAL = config.BASE_URL


def mint(cookie: str) -> dict:
    """cookie -> {accesstoken, refresstoken}. Raises on HTTP error."""
    r = auth.validate_xcd(cookie)
    return r


def certify(token: str) -> dict:
    auth.set_session_token(token)
    return auth.login()


def keepalive(interval: int) -> None:
    """Ping shake-hand forever; print verdict. A 200 keeps the session alive."""
    n = 0
    while True:
        n += 1
        try:
            r = auth.shake_hand()
            print(f"[{n}] shake-hand -> {r}", flush=True)
        except Exception as e:
            print(f"[{n}] shake-hand ERR {e}", flush=True)
        time.sleep(interval)


def demo() -> None:
    """Call a handful of real endpoints to prove the token works."""
    calls = [
        ("GET  /player", lambda: config.get("/player")),
        ("GET  /player/getInventory", lambda: config.get("/player/getInventory")),
        ("GET  /card/all", lambda: config.get("/card/all")),
    ]
    for label, fn in calls:
        try:
            r = fn()
            print(f"  {label} -> {str(r)[:160]}", flush=True)
        except Exception as e:
            print(f"  {label} ERR {e}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookie")
    ap.add_argument("--token")
    ap.add_argument("--keepalive", type=int, default=0,
                    help="seconds between shake-hand pings; 0 = no keep-alive")
    args = ap.parse_args()

    if args.cookie:
        print("== mint token from cookie ==")
        r = mint(args.cookie)
        token = r.get("accesstoken")
        if not token:
            print("XCD FAILED:", r)
            return 1
        print("  accesstoken:", token)
        print("== certify via /auth/login ==")
        print("  login:", certify(token))
    elif args.token:
        auth.set_session_token(args.token)
    else:
        ap.error("need --cookie or --token")

    print("== API demo ==")
    demo()

    if args.keepalive:
        print(f"== keep-alive every {args.keepalive}s (Ctrl-C to stop) ==")
        keepalive(args.keepalive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
