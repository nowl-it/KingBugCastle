"""The Google web-login flow: /glogin -> Google -> /glogin/callback -> deep link.

Real Google is never contacted here; the token exchange is swapped for a stub so
the flow is exercised end to end without a live OAuth client. What matters:

  * unconfigured -> a clear 503, not a crash or a broken redirect.
  * /glogin sends the browser to Google's consent screen with a signed state.
  * the callback turns a Google `sub` into `google_<sub>` and hands it back as a
    kingbugcastle://auth deep link.
  * a forged or stale state is refused (the CSRF guard).
  * the account id the flow emits is exactly what the multi-account login keys a
    save on, so a Google sign-in lands on its own save.
"""
import sys, tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"
playerdb.init()

import base64, json
import google_login
import server
from fastapi.testclient import TestClient

client = TestClient(server.app, client=("127.0.0.1", 50000), follow_redirects=False)


def _configure():
    google_login.CLIENT_ID = "web-client.apps.googleusercontent.com"
    google_login.CLIENT_SECRET = "secret"
    google_login.PUBLIC_URL = "https://kgc.example.com"


def _fake_id_token(sub):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
    return f"header.{payload}.sig"


def check_unconfigured_is_a_clear_503():
    """503 plus the env vars to set. Asserted on the variable NAMES, not the prose -
    the wording is user-facing copy and should be free to change."""
    google_login.CLIENT_ID = google_login.CLIENT_SECRET = google_login.PUBLIC_URL = ""
    r = client.get("/glogin")
    assert r.status_code == 503, r.status_code
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GLOGIN_PUBLIC_URL"):
        assert name in r.text, f"the 503 does not say to set {name}"
    print("ok off: unconfigured /glogin explains itself with 503")


def check_start_redirects_to_google_with_a_signed_state():
    _configure()
    r = client.get("/glogin")
    assert r.status_code in (302, 307), r.status_code
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/"), loc
    q = parse_qs(urlparse(loc).query)
    assert q["client_id"][0] == google_login.CLIENT_ID
    assert q["redirect_uri"][0] == "https://kgc.example.com/glogin/callback"
    assert google_login.check_state(q["state"][0]), "state is not verifiable"
    print("ok start: 302 to Google, redirect_uri and signed state present")


def check_callback_parks_the_account_id_for_the_poller():
    """The callback resolves the Google sub to google_<sub>, parks it for the app's
    poller (/glogin/pending), and deep-links back to foreground the app. The client's
    own Auth(id) does the real login - so the flow carries the id, not a token."""
    _configure()
    google_login._exchange_code = lambda code, redirect_uri: {"id_token": _fake_id_token("42abc")}
    state = google_login.make_state()
    r = client.get(f"/glogin/callback?code=xyz&state={state}")
    assert r.status_code == 200 and "kingbugcastle://auth" in r.text, r.text[:200]
    p = client.get("/glogin/pending")
    assert p.text == "google_42abc", f"poller would get {p.text!r}, not google_42abc"
    assert client.get("/glogin/pending").text == "", "pending id was not cleared after read"
    print("ok callback: sub 42abc -> pending id google_42abc (cleared after one read)")


def check_a_forged_state_is_refused():
    _configure()
    google_login._PENDING["id"] = ""
    google_login._exchange_code = lambda *a, **k: {"id_token": _fake_id_token("x")}
    r = client.get("/glogin/callback?code=xyz&state=forged.nonce.deadbeef")
    assert r.status_code == 400, r.status_code
    # The part that matters is not the wording but that nothing was parked: a forged
    # state must be refused BEFORE the exchange, so the poller has nothing to pick up.
    assert google_login._PENDING["id"] == "", "a forged state still parked an account id"
    print("ok csrf: a forged state is rejected before any token exchange")


def check_the_emitted_id_lands_on_its_own_save():
    """The account id from the flow must be what _uid_for_login keys a save on, or
    the whole redirect is cosmetic."""
    saved = server.MULTIPLAYER
    try:
        server.MULTIPLAYER = True
        acct = google_login.account_id_for_sub("777")
        # two prior accounts exist so adoption does not fire - this must be its own save
        playerdb.bind_login("someone", "p-existing")
        playerdb.save("p-existing", {"uid": "p-existing"})
        uid = server._uid_for_login(acct, None, server_type := 1)
        assert uid == "p-" + server.hashlib.sha1(acct.encode()).hexdigest()[:12]
        assert playerdb.uid_for_login(acct) == uid, "the Google id was not bound"
    finally:
        server.MULTIPLAYER = saved
    print("ok bind: google_777 resolves to its own per-account save")


if __name__ == "__main__":
    check_unconfigured_is_a_clear_503()
    check_start_redirects_to_google_with_a_signed_state()
    check_callback_parks_the_account_id_for_the_poller()
    check_a_forged_state_is_refused()
    check_the_emitted_id_lands_on_its_own_save()
    print("\nall google-login checks passed")
