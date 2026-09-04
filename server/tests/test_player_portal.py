"""Player portal Phase 1 checks against a throwaway player database."""
import base64
import json
import pathlib
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient

_SERVER = pathlib.Path(__file__).resolve().parent.parent
for _path in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _text = str(_path)
    if _text not in sys.path:
        sys.path.insert(0, _text)

import playerdb

_TMP = tempfile.TemporaryDirectory()
playerdb.DB_PATH = pathlib.Path(_TMP.name) / "players.db"
playerdb.init()

import google_login
import playerportal

app = FastAPI()
google_login.register_portal(app)
playerportal.register(app)
client = TestClient(app, base_url="https://testserver", follow_redirects=False,
                    client=("127.0.0.1", 54001))


def _seed(uid, login_id, name):
    playerdb.save(uid, {"uid": uid, "name": name, "castleName": "Keep", "cards": {},
                        "inventory": {"itemIds": [], "counts": []}})
    playerdb.bind_login(login_id, uid)


def _fake_id_token(sub):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
    return f"header.{payload}.sig"


def check_guest_access_login_and_password_rotation():
    _seed("p-guest", "Guest_ABC", "Guest King")
    created = playerdb.portal_guest_access("Guest_ABC", "guestking", "temporary-1")
    assert created["must_change_password"]

    r = client.post("/portal/api/auth/login", json={"username": "guestking", "password": "temporary-1"})
    assert r.status_code == 200, r.text
    assert r.json()["mustChangePassword"] is True
    assert r.json()["player"]["loginId"] == "Guest_ABC"
    assert client.get("/portal/api/auth/whoami").json()["player"]["uid"] == "p-guest"

    r = client.post("/portal/api/auth/password", json={"oldPassword": "temporary-1", "newPassword": "new-password-2"})
    assert r.status_code == 200 and r.json()["signInAgain"]
    assert client.get("/portal/api/auth/whoami").json()["authenticated"] is False
    assert client.post("/portal/api/auth/login", json={"username": "guestking", "password": "temporary-1"}).status_code == 401
    r = client.post("/portal/api/auth/login", json={"username": "guestking", "password": "new-password-2"})
    assert r.status_code == 200 and r.json()["mustChangePassword"] is False
    print("ok portal guest: issued credential maps to its game save and rotates safely")


def check_guest_login_lockout_is_persistent():
    _seed("p-lock", "Guest_LOCK", "Lock King")
    playerdb.portal_guest_access("Guest_LOCK", "lockking", "temporary-3")
    for _ in range(playerdb.PLAYER_PORTAL_MAX_FAILURES):
        r = client.post("/portal/api/auth/login", json={"username": "lockking", "password": "wrong-password"})
        assert r.status_code in (401, 429), r.text
    r = client.post("/portal/api/auth/login", json={"username": "lockking", "password": "temporary-3"})
    assert r.status_code == 429, r.text
    print("ok portal lockout: password and source-address failures lock for ten minutes")


def check_google_portal_login_uses_existing_game_account():
    _seed("p-google", "google_42", "Google King")
    google_login.CLIENT_ID = "test-client"
    google_login.CLIENT_SECRET = "test-secret"
    google_login.PUBLIC_URL = "https://testserver"
    google_login.PORTAL_PUBLIC_URL = "https://testserver"
    google_login._exchange_code = lambda *args: {"id_token": _fake_id_token("42")}

    r = client.get("/portal/api/auth/google")
    assert r.status_code in (302, 307), r.text
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    assert google_login.state_target(state) == "portal"
    r = client.get("/portal/api/auth/google/callback", params={"code": "ok", "state": state})
    assert r.status_code == 303 and r.headers["location"] == "/player", r.text
    assert client.get("/portal/api/auth/whoami").json()["player"]["loginId"] == "google_42"
    print("ok portal google: same Google sub resolves the existing game account")


def check_google_portal_refuses_an_account_that_never_entered_game():
    google_login.CLIENT_ID = "test-client"
    google_login.CLIENT_SECRET = "test-secret"
    google_login.PUBLIC_URL = "https://testserver"
    google_login.PORTAL_PUBLIC_URL = "https://testserver"
    google_login._exchange_code = lambda *args: {"id_token": _fake_id_token("new")}
    r = client.get("/portal/api/auth/google/callback", params={"code": "ok", "state": google_login.make_state("portal")})
    assert r.status_code == 403 and "Game account not found" in r.text
    print("ok portal Google: a dashboard login never mints a separate game save")


if __name__ == "__main__":
    check_guest_access_login_and_password_rotation()
    check_guest_login_lockout_is_persistent()
    check_google_portal_login_uses_existing_game_account()
    check_google_portal_refuses_an_account_that_never_entered_game()
    print("\nall player portal Phase 1 checks passed")
