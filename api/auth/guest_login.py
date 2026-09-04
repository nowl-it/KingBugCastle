"""Create (or reuse) a guest session on the official API and store its accesstoken.

Flow mirrors the proven capture script server/capture/dump_real_api.py:

    POST /auth/register {type:4, id:"", userName, castleName, postfixes} -> loginId (+token)
    GET  /auth/xcdSeed
    GET  /auth?id=<loginId>&version=&cookie=&platform=Android -> accessToken

The returned loginId is persisted and reused: later runs re-present it via
GET /auth?id=... instead of creating another account.

NOTE (verified 2026-08-24): account creation is fully scriptable, but the
official API issues accesstokens ONLY to requests with a valid XIGNCODE cookie
(401 WrongTokenError otherwise) - that cookie is produced by the native SDK in
the real client and cannot be generated here. To get a working session, harvest
a token from a genuine client login: api/auth/token_harvester.py.

    python3 api/auth/guest_login.py            # reuse saved account, mint token
    python3 api/auth/guest_login.py --fresh    # force a brand-new guest account

Writes repo-root captured_guest.json (loginId/token/expiredAt) and
captured_token.txt (read by api.config._autoload_token).
"""
import argparse
import json
import os
import random
import string
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "captured_guest.json")
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "..", "captured_token.txt")

# version int scheme major*10000 + minor*100 + patch (169003 == v169.0.03).
VERSION_INT = int("".join(config.VERSION.split(".")))


def _state() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except OSError:
        return {}


def _save(state: dict):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=1)
    with open(TOKEN_PATH, "w") as f:
        f.write(state.get("token") or "")


def _rand_name(n=8) -> str:
    # Official server rejects arbitrary names (WrongKingName); this shape is proven.
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def _mint(login_id: str) -> dict:
    """GET /auth - re-present a known login id, get a fresh accesstoken."""
    resp = config.get("/auth", params={
        "id": login_id, "version": config.VERSION, "cookie": "", "platform": "Android",
    })
    if not isinstance(resp, dict) or not resp.get("accessToken"):
        raise RuntimeError(f"auth({login_id}): no accessToken, got {resp!r} "
                           "(official API requires a XIGNCODE cookie only the real "
                           "client can produce; harvest a session token instead - "
                           "see api/auth/token_harvester.py)")
    config.set_auth_token(resp["accessToken"])
    return resp


def _register() -> tuple[str, dict]:
    """POST /auth/register - server assigns loginId when id is empty."""
    resp = config.post("/auth/register", {
        "type": 4,
        "id": "",
        "userName": _rand_name(),
        "castleName": _rand_name(),
        "kingPostfix": 1,
        "castlePostfix": 1,
        "version": VERSION_INT,
    })
    if not isinstance(resp, dict) or not resp.get("loginId"):
        raise RuntimeError(f"register failed: {resp!r}")
    config.get("/auth/xcdSeed", params={"version": VERSION_INT})
    login_id = resp["loginId"]
    if not resp.get("accessToken"):
        resp.update(_mint(login_id))
    else:
        config.set_auth_token(resp["accessToken"])
    return login_id, resp


def ensure_token(force_new: bool = False) -> dict:
    """Return session state, reusing the same guest account across runs."""
    state = {} if force_new else _state()
    login_id = state.get("loginId")
    if not force_new and login_id:
        try:
            resp = _mint(login_id)
        except Exception:
            login_id, resp = _register()
    else:
        login_id, resp = _register()
    state.update({"loginId": login_id, "token": resp.get("accessToken"),
                  "expiredAt": resp.get("expiredAt"), "serverTime": resp.get("serverTime")})
    _save(state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true", help="create a new guest account")
    args = parser.parse_args()
    try:
        state = ensure_token(args.fresh)
    except Exception as e:
        print(f"ERR: {e}", file=sys.stderr)
        return 1
    tok = state.get("token") or ""
    print(json.dumps({
        "loginId": state.get("loginId"),
        "token": f"{tok[:6]}...{tok[-4:]}" if len(tok) > 12 else "(short)",
        "expiredAt": state.get("expiredAt"),
        "savedTo": [os.path.basename(STATE_PATH), os.path.basename(TOKEN_PATH)],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
