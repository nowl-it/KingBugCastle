"""Dashboard sign-in: accounts, cookies, and who is refused.

Before this the only gate was KGC_ADMIN_TOKEN or "the request came from loopback".
Behind a tunnel or a reverse proxy every request looks like loopback, so that
fallback let any remote player rewrite or delete saves.
"""
import sys, tempfile, pathlib

_SERVER = pathlib.Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)
import playerdb
playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "t.db"
playerdb.init()

import dashboard
from fastapi.testclient import TestClient

# TestClient's default peer is the literal "testclient", which is NOT loopback and
# would silently fake a pass on every loopback check.
LOCAL = lambda: TestClient(dashboard.app, client=("127.0.0.1", 40000))
REMOTE = lambda: TestClient(dashboard.app, client=("10.0.0.9", 40000))


def _reset():
    for a in playerdb.admin_list():
        playerdb.admin_delete(a["username"])
    dashboard._login_hits.clear()


def test_no_admins_loopback_only():
    _reset()
    assert LOCAL().get("/api/players").status_code == 200
    assert REMOTE().get("/api/players").status_code == 401


def test_admins_exist_password_required_even_on_loopback():
    _reset()
    playerdb.admin_create("root", "correct horse")
    c = LOCAL()
    assert c.get("/api/players").status_code == 401, "loopback bypassed an existing account"
    assert c.post("/api/auth/login", json={"username": "root", "password": "nope"}).status_code == 401
    r = c.post("/api/auth/login", json={"username": "root", "password": "correct horse"})
    assert r.status_code == 200 and dashboard.SESSION_COOKIE in r.cookies
    assert c.get("/api/players").status_code == 200
    assert c.get("/api/auth/whoami").json()["user"] == "root"
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/players").status_code == 401


def test_session_works_from_a_remote_peer():
    """The whole point: a signed-in operator can be anywhere."""
    _reset()
    playerdb.admin_create("root", "correct horse")
    c = REMOTE()
    c.post("/api/auth/login", json={"username": "root", "password": "correct horse"})
    assert c.get("/api/players").status_code == 200


def test_whoami_is_open_but_leaks_nothing():
    _reset()
    playerdb.admin_create("root", "correct horse")
    body = REMOTE().get("/api/auth/whoami").json()
    assert body["authenticated"] is False and body["user"] is None
    assert body["hasAdmins"] is True          # the UI needs this to pick a login form
    assert "root" not in str(body)


def test_whoami_tells_the_ui_there_is_nothing_to_sign_in_with():
    """The `locked` gate in app.js.

    With no admin account and no token, a remote peer is refused and there is no
    credential in existence to type. The UI used to draw a sign-in form here, which
    could never succeed - it branches on exactly these three fields, so their shape
    is a contract, not an implementation detail.
    """
    _reset()
    assert not dashboard.ADMIN_TOKEN, "this test assumes no KGC_ADMIN_TOKEN"
    body = REMOTE().get("/api/auth/whoami").json()
    assert body["authenticated"] is False
    assert body["hasAdmins"] is False
    assert body["tokenMode"] is False
    # ...and the reason says what to do about it, since that is all the UI can show.
    assert "admin" in (body["reason"] or "").lower()


def test_first_admin_can_be_created_from_loopback_then_locks_the_door():
    """The Account tab's create form, end to end.

    Creating the first admin from loopback is what moves the dashboard off its
    weakest rung; before this UI existed the only way was the --create-admin CLI.
    """
    _reset()
    c = LOCAL()
    assert c.get("/api/auth/admins").json()["admins"] == []
    r = c.post("/api/auth/admins", json={"username": "op", "password": "hunter2hunter2"})
    assert r.status_code == 200, r.text
    assert [a["username"] for a in r.json()["admins"]] == ["op"]
    # Creating it immediately closes loopback, so the same client is now refused.
    assert c.get("/api/players").status_code == 401, "loopback still open after an admin existed"
    assert c.post("/api/auth/login",
                  json={"username": "op", "password": "hunter2hunter2"}).status_code == 200
    assert c.get("/api/players").status_code == 200


def test_short_passwords_are_refused():
    _reset()
    r = LOCAL().post("/api/auth/admins", json={"username": "op", "password": "short"})
    assert r.status_code == 400
    assert playerdb.admin_count() == 0, "a rejected password still created the account"


def test_login_is_rate_limited():
    _reset()
    playerdb.admin_create("root", "correct horse")
    c = REMOTE()
    codes = [c.post("/api/auth/login", json={"username": "root", "password": "x"}).status_code
             for _ in range(12)]
    assert 429 in codes, f"brute force was never throttled: {codes}"
    _reset()


def test_cannot_delete_the_last_admin():
    _reset()
    playerdb.admin_create("root", "correct horse")
    c = LOCAL()
    c.post("/api/auth/login", json={"username": "root", "password": "correct horse"})
    assert c.delete("/api/auth/admins/root").status_code == 400
    playerdb.admin_create("second", "another password")
    assert c.delete("/api/auth/admins/root").status_code == 400, "deleted the signed-in account"
    assert c.delete("/api/auth/admins/second").status_code == 200


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("\nall dashboard auth checks passed")
