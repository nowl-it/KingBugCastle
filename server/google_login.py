"""Google login for the private server, via a web OAuth flow the client opens.

Why this exists: real Google Play Games sign-in only authenticates an app whose
package + signing cert are registered in Google Play Console, which the repacked
build is not, so the in-game Google button dies inside the Google SDK. A *web*
OAuth client has no such requirement - it authenticates a browser, not the APK.
So the client's Google button is repointed to open `/glogin` here; the user signs
in with Google in the browser; and we hand the resulting stable account id back to
the app through a deep link.

Flow:
    client Google button --OpenURL--> GET /glogin
        -> 302 to Google's consent screen (our web client_id, signed `state`)
    Google -> GET /glogin/callback?code&state
        -> exchange code for an id_token at Google's token endpoint (server-side,
           over TLS, so the response is trusted without re-verifying the JWT sig)
        -> read the stable `sub` claim
        -> 200 HTML that navigates to  kingbugcastle://auth?id=google_<sub>
    the app's deep-link bridge takes that id and calls RestAPI.Auth(id), which the
    server already resolves to that account's own save (KGC_MULTIPLAYER).

The account id handed to the app is `google_<sub>`. `sub` is stable per (user,
OAuth client), so the same Google account restores the same save on any device -
which is the whole reason to log in with Google rather than as a Guest.

Config (env):
    GOOGLE_CLIENT_ID       web OAuth client id      (required to enable)
    GOOGLE_CLIENT_SECRET   web OAuth client secret  (required to enable)
    GLOGIN_PUBLIC_URL      public base the browser reaches, e.g.
                           https://kgc.example.com  (its /glogin/callback must be
                           an authorised redirect URI on the OAuth client)
    GLOGIN_SCHEME          deep-link scheme back into the app (default kingbugcastle)
    GLOGIN_STATE_SECRET    HMAC key for the CSRF state (default: random per boot)

Setup in Google Cloud (once, by whoever owns the server):
    APIs & Services -> Credentials -> Create OAuth client -> **Web application**
    Authorised redirect URI:  <GLOGIN_PUBLIC_URL>/glogin/callback
    Scopes needed: openid  (email/profile optional, only for a nicer name)
"""
import base64, hashlib, hmac, json, os, secrets, time, urllib.parse, urllib.request

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
PUBLIC_URL = os.environ.get("GLOGIN_PUBLIC_URL", "").rstrip("/")
SCHEME = os.environ.get("GLOGIN_SCHEME", "kingbugcastle")
_STATE_SECRET = (os.environ.get("GLOGIN_STATE_SECRET") or secrets.token_hex(16)).encode()

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_TTL = 600   # a consent screen the user leaves open for 10 min is plenty

# The token exchange is patched out in tests; kept as a module attribute so a test
# can swap it without a live Google.
def _exchange_code(code, redirect_uri):
    """Trade an auth code for Google's id_token. The response comes straight from
    Google's token endpoint over TLS, so its id_token is trusted as-is - we do not
    re-verify the JWT signature. ponytail: that trust holds ONLY because we fetched
    it ourselves; verify via JWKS if an id_token ever arrives from elsewhere."""
    data = urllib.parse.urlencode({
        "code": code, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def enabled():
    return bool(CLIENT_ID and CLIENT_SECRET and PUBLIC_URL)


def _b64url_json(segment):
    """Decode one base64url JWT segment (payload) to a dict, padding as needed."""
    pad = "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(segment + pad))


def sub_from_id_token(id_token):
    """The stable Google user id (`sub`) out of the JWT payload. Trusted because the
    token came from _exchange_code, i.e. straight from Google over TLS."""
    payload = _b64url_json(id_token.split(".")[1])
    sub = str(payload.get("sub") or "")
    if not sub:
        raise ValueError("id_token has no sub")
    return sub


def account_id_for_sub(sub):
    """The login id the app sends and the server keys a save on. Prefixed so a
    Google account can never collide with a Guest_xxx id."""
    return "google_" + sub


def make_state():
    """A signed, timestamped nonce. Stateless on purpose: the two uvicorn processes
    (:8080, :8443) share no memory, and a browser redirect can land the start and
    the callback on different ones, so an in-memory store would drop it."""
    raw = f"{int(time.time())}.{secrets.token_hex(8)}"
    sig = hmac.new(_STATE_SECRET, raw.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{raw}.{sig}"


def check_state(state):
    try:
        ts, nonce, sig = state.split(".")
    except (ValueError, AttributeError):
        return False
    raw = f"{ts}.{nonce}"
    good = hmac.new(_STATE_SECRET, raw.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, good):
        return False
    return abs(time.time() - int(ts)) <= STATE_TTL


def _redirect_uri():
    return f"{PUBLIC_URL}/glogin/callback"


def authorize_url():
    q = urllib.parse.urlencode({
        "client_id": CLIENT_ID, "redirect_uri": _redirect_uri(),
        "response_type": "code", "scope": "openid",
        "state": make_state(), "prompt": "select_account",
    })
    return f"{AUTH_URL}?{q}"


def deep_link(account_id):
    return f"{SCHEME}://auth?id={urllib.parse.quote(account_id)}"


_RETURN_PAGE = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>King Bug Castle</title>
<style>body{{font-family:system-ui;text-align:center;padding:2rem;background:#111;color:#eee}}
a.btn{{display:inline-block;margin-top:1.5rem;padding:.9rem 1.6rem;background:#4a7;color:#fff;
border-radius:.6rem;text-decoration:none;font-weight:600}}</style>
<h2>Signed in with Google</h2>
<p>Returning to the game...</p>
<a class=btn href="{link}">Open King Bug Castle</a>
<script>location.href={link_js};</script>
"""


def return_page(account_id):
    link = deep_link(account_id)
    return _RETURN_PAGE.format(link=link, link_js=json.dumps(link))


def register(app):
    """Add /glogin and /glogin/callback to the FastAPI app. No-op-ish if unconfigured
    (the routes exist but explain they are off)."""
    from fastapi.responses import HTMLResponse, RedirectResponse

    @app.get("/glogin")
    def glogin_start():
        if not enabled():
            return HTMLResponse(
                "<h3>Google login is not configured.</h3><p>Set GOOGLE_CLIENT_ID, "
                "GOOGLE_CLIENT_SECRET and GLOGIN_PUBLIC_URL. See "
                "docs/multi-account-login.md.</p>", status_code=503)
        return RedirectResponse(authorize_url())

    @app.get("/glogin/callback")
    def glogin_callback(code: str = "", state: str = "", error: str = ""):
        if error:
            return HTMLResponse(f"<h3>Google sign-in was cancelled.</h3><p>{error}</p>",
                                status_code=400)
        if not enabled():
            return HTMLResponse("<h3>Google login is not configured.</h3>", status_code=503)
        if not check_state(state):
            return HTMLResponse("<h3>Login expired or invalid.</h3><p>Please try "
                                "again from the game.</p>", status_code=400)
        try:
            tok = _exchange_code(code, _redirect_uri())
            sub = sub_from_id_token(tok["id_token"])
        except Exception as e:                      # noqa: BLE001 - user-facing
            return HTMLResponse(f"<h3>Could not verify the Google sign-in.</h3>"
                                f"<pre>{type(e).__name__}</pre>", status_code=502)
        return HTMLResponse(return_page(account_id_for_sub(sub)))


if __name__ == "__main__":   # self-check: state round-trip + id derivation + return page
    s = make_state()
    assert check_state(s), "a freshly minted state must verify"
    assert not check_state(s[:-1] + ("0" if s[-1] != "0" else "1")), "tampered sig passed"
    assert not check_state("garbage") and not check_state("")
    old = f"{int(time.time()) - STATE_TTL - 5}.{secrets.token_hex(8)}"
    old_sig = hmac.new(_STATE_SECRET, old.encode(), hashlib.sha256).hexdigest()[:16]
    assert not check_state(f"{old}.{old_sig}"), "an expired state passed"

    # A real Google id_token is header.payload.sig; only the payload is read.
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "1088x7"}).encode()).rstrip(b"=").decode()
    assert sub_from_id_token(f"h.{payload}.s") == "1088x7"
    assert account_id_for_sub("1088x7") == "google_1088x7"
    assert deep_link("google_1088x7") == "kingbugcastle://auth?id=google_1088x7"
    assert "kingbugcastle://auth?id=google_1088x7" in return_page("google_1088x7")
    print("google_login self-check ok")
