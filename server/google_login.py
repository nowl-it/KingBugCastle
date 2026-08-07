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

Config. Easiest way: drop the JSON Google gives you at

    server/secrets/google_oauth.json     (gitignored; `GOOGLE_OAUTH_FILE` overrides)

exactly as downloaded - it carries the id, the secret AND the redirect URI you
registered, so nothing has to be retyped and the redirect can't drift out of sync
with the Console. Environment variables override the file when both are present:

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
import base64, hashlib, hmac, json, os, pathlib, secrets, time, urllib.parse, urllib.request

# --- config, from the downloaded client JSON and/or the environment --------------
SECRETS_DIR = pathlib.Path(__file__).resolve().parent / "secrets"
OAUTH_FILE = pathlib.Path(os.environ.get("GOOGLE_OAUTH_FILE")
                          or SECRETS_DIR / "google_oauth.json")


def load_client_file(path=None):
    """(client_id, client_secret, public_url) out of Google's downloaded JSON.

    The file is `{"web": {...}}` for a web client and `{"installed": {...}}` for the
    desktop kind. Only "web" works here - an installed/Android client is exactly the
    one that needs a Play Console signing cert - so read that key and no other, and
    say so rather than half-working.

    public_url comes from `redirect_uris[0]` minus the /glogin/callback suffix. That
    is deliberate: the redirect_uri we send Google must byte-match one it has on
    file, and deriving it from the same file removes the only way to get that wrong.
    """
    path = pathlib.Path(path or OAUTH_FILE)
    if not path.exists():
        return "", "", ""
    try:
        blob = json.loads(path.read_text())
    except (OSError, ValueError) as e:                       # noqa: BLE001
        print(f"[glogin] {path.name} is not readable JSON: {e}", flush=True)
        return "", "", ""
    if "web" not in blob:
        kind = ", ".join(blob) or "nothing"
        print(f"[glogin] {path.name} has no 'web' client (found: {kind}). Create an "
              f"OAuth client of type 'Web application' - the Android/desktop kinds "
              f"cannot authenticate a repacked build.", flush=True)
        return "", "", ""
    web = blob["web"]
    uris = web.get("redirect_uris") or []
    base = ""
    for uri in uris:
        if uri.endswith("/glogin/callback"):
            base = uri[: -len("/glogin/callback")]
            break
    if uris and not base:
        print(f"[glogin] none of the redirect_uris in {path.name} end in "
              f"/glogin/callback: {uris}", flush=True)
    return web.get("client_id", ""), web.get("client_secret", ""), base.rstrip("/")


_f_id, _f_secret, _f_url = load_client_file()

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID") or _f_id
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET") or _f_secret
PUBLIC_URL = (os.environ.get("GLOGIN_PUBLIC_URL") or _f_url).rstrip("/")
SCHEME = os.environ.get("GLOGIN_SCHEME", "kingbugcastle")
# Dev mode: exercise the whole client loop (button -> web -> deep link -> login)
# WITHOUT a real Google OAuth client. /glogin serves a page with a couple of test
# accounts whose buttons fire the deep link directly. Never leave this on in prod -
# it lets anyone log in as any dev id.
DEV = os.environ.get("GLOGIN_DEV") == "1"
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


# One page shell for every screen this module serves. These are the only pages a
# player ever sees from the server, usually on a phone, often over a slow tunnel -
# so: one self-contained file, no external CSS, no font or script fetch. The palette
# matches the dashboard so the two do not look like different products.
_PAGE = """<!doctype html>
<html lang=en><head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<meta name=color-scheme content=dark>
<meta name=theme-color content="#0b0f17">
<meta name=robots content="noindex, nofollow">
<title>{title}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
padding:24px;background:#0b0f17;color:#e6ecf7;
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.card{{width:100%;max-width:26rem;background:linear-gradient(180deg,#151d2e,#111725);
border:1px solid #1e2739;border-radius:14px;padding:28px 24px;text-align:center;
box-shadow:0 8px 30px rgba(0,0,0,.35)}}
.mark{{width:44px;height:44px;margin:0 auto 16px;border-radius:12px;
background:linear-gradient(135deg,#4f8cff,#9333ea);display:flex;align-items:center;
justify-content:center;font-weight:700;font-size:15px;color:#fff}}
h1{{margin:0 0 8px;font-size:17px;font-weight:650}}
p{{margin:0 0 4px;color:#a3b0c9;font-size:13.5px}}
p.small{{color:#6d7c99;font-size:12px;margin-top:14px}}
code{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:#7aa8ff;
background:rgba(79,140,255,.1);padding:1px 5px;border-radius:4px}}
.btn{{display:block;margin:10px 0 0;padding:.85rem 1rem;border-radius:9px;
text-decoration:none;font-weight:600;font-size:14px;color:#fff;background:#1a2333}}
.btn.go{{background:linear-gradient(135deg,#4f8cff,#3b6fd4)}}
.btn.alt{{background:#1a2333;border:1px solid #26314a;color:#e6ecf7}}
.stack{{margin-top:18px}}
.bad h1{{color:#f87171}}
</style></head>
<body><div class="{cls}">
<div class=mark>KBC</div>
{body}
</div>{tail}</body></html>
"""


def _page(title, body, tail="", bad=False):
    """Render one of the pages above. `tail` is for the one script we ever emit."""
    return _PAGE.format(title=title, body=body, tail=tail,
                        cls="card bad" if bad else "card")


# Application.absoluteURL is stripped from the client (the game never uses it), so
# the app can't read the return deep link. Instead the picked ACCOUNT ID is parked
# here; the app's native poller fetches it from /glogin/pending and drives the
# client's own Scene_Login.Auth(id) - the full auth handshake, ending at the lobby.
# We pass the id, not a session token: just setting a token skips /auth, and the
# client bails with "Unable to fetch player data". Single slot: a private server
# with one player logging in at a time.
# ponytail: one global slot, no per-device keying. Key it by a device id in the
# deep link if two people ever log in at the same second.
def _client_ip(request):
    peer = request.client.host if request.client else "-"
    fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or peer


def _pending_file(ip: str):
    import hashlib
    safe = hashlib.md5(ip.encode()).hexdigest()
    return pathlib.Path(__file__).parent / "state" / f".glogin_pending_{safe}"

def _set_pending(ip: str, account_id: str):
    _pending_file(ip).write_text(account_id)

def _get_and_clear_pending(ip: str):
    f = _pending_file(ip)
    if f.exists():
        acc = f.read_text().strip()
        try:
            f.unlink()
        except OSError:
            pass
        return acc
    
    # Fallback for IPv4 vs IPv6 mismatch (e.g. Chrome uses IPv6 via Cloudflare, Unity uses IPv4).
    # If the strict IP hash file is not found, look for ANY recent pending file (<=60s).
    state_dir = pathlib.Path(__file__).parent / "state"
    pending_files = list(state_dir.glob(".glogin_pending_*"))
    if pending_files:
        # Sort by modification time, newest first
        pending_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        now = time.time()
        for fallback_file in pending_files:
            mtime = fallback_file.stat().st_mtime
            if now - mtime > 60:
                try:
                    fallback_file.unlink()
                except OSError:
                    pass
                continue
            acc = fallback_file.read_text().strip()
            try:
                fallback_file.unlink()
            except OSError:
                pass
            if acc:
                return acc
        
    # Super fallback for local development split-brain:
    # If Chrome on the phone uses Secure DNS, it bypasses the hosts file and completes 
    # OAuth on the public VPS. The Unity game respects the hosts file and polls the local 
    # laptop. If we are running locally and have no pending files, try asking the VPS!
    try:
        import urllib.request
        req = urllib.request.Request(f"{PUBLIC_URL}/glogin/pending")
        with urllib.request.urlopen(req, timeout=3) as r:
            remote_acc = r.read().decode("utf-8").strip()
            if remote_acc:
                return remote_acc
    except Exception:
        pass
        
    return ""


def return_page(request, account_id):
    """Park the account id for the poller, and hand back a page that deep-links back
    into the app to foreground it (the id travels via the poll, not the link)."""
    _set_pending(_client_ip(request), account_id)
    link = f"{SCHEME}://auth"
    return _page(
        "Signed in - King Bug Castle",
        "<h1>Signed in</h1>"
        "<p>Taking you back to the game.</p>"
        f"<div class=stack><a class='btn go' href='{link}'>Open King Bug Castle</a></div>"
        "<p class=small>If nothing happens, switch back to the game yourself - "
        "you are already signed in.</p>",
        # The redirect is what normally returns the player; the button is the fallback
        # for browsers that refuse to follow a custom scheme without a real tap.
        tail=f"<script>location.href={json.dumps(link)};</script>")


def dev_page():
    """A no-Google stand-in for the consent screen: buttons that fire the deep link
    for a few fixed dev accounts, so the client loop can be tested end to end."""
    ids = ["google_devA", "google_devB", "google_devC"]
    buttons = "".join(
        f"<a class='btn alt' href='/glogin/go?id={i}'>Sign in as {i}</a>" for i in ids)
    return _page(
        "Dev login - King Bug Castle",
        "<h1>Dev login</h1>"
        "<p>Real Google is off (<code>GLOGIN_DEV=1</code>). Pick a test account.</p>"
        f"<div class=stack>{buttons}</div>"
        "<p class=small>Each id keeps its own save, exactly like a real Google account.</p>")


def error_page(title, detail, hint=""):
    """Every failure a player can hit, in the same shell as the success page. A bare
    <h3> used to be the whole response, which reads as a broken server rather than a
    login that needs retrying."""
    hint_html = f"<p class=small>{hint}</p>" if hint else ""
    return _page(f"{title} - King Bug Castle",
                 f"<h1>{title}</h1><p>{detail}</p>{hint_html}", bad=True)


def register(app):
    """Add /glogin and /glogin/callback to the FastAPI app. No-op-ish if unconfigured
    (the routes exist but explain they are off)."""
    from fastapi import Request
    from fastapi.responses import HTMLResponse, RedirectResponse

    _NOT_CONFIGURED = (
        "Google sign-in is turned off on this server.",
        "The operator sets <code>GOOGLE_CLIENT_ID</code>, <code>GOOGLE_CLIENT_SECRET</code> "
        "and <code>GLOGIN_PUBLIC_URL</code> to enable it, or <code>GLOGIN_DEV=1</code> to "
        "test without Google. See docs/multi-account-login.md.")

    @app.get("/glogin")
    def glogin_start():
        if not enabled():
            if DEV:
                return HTMLResponse(dev_page())
            return HTMLResponse(error_page("Not available", *_NOT_CONFIGURED),
                                status_code=503)
        return RedirectResponse(authorize_url())

    @app.get("/glogin/callback")
    def glogin_callback(request: Request, code: str = "", state: str = "", error: str = ""):
        if error:
            return HTMLResponse(
                error_page("Sign-in cancelled",
                           "Google did not complete the sign-in.",
                           f"Reason: <code>{error}</code>. Tap the Google button in the "
                           "game to try again."), status_code=400)
        if not enabled():
            return HTMLResponse(error_page("Not available", *_NOT_CONFIGURED),
                                status_code=503)
        if not check_state(state):
            return HTMLResponse(
                error_page("Sign-in expired",
                           "This sign-in link is no longer valid.",
                           "It is good for 10 minutes. Tap the Google button in the game "
                           "to start a new one."), status_code=400)
        try:
            tok = _exchange_code(code, _redirect_uri())
            sub = sub_from_id_token(tok["id_token"])
        except Exception as e:                      # noqa: BLE001 - user-facing
            # The exception type only; the body can carry the client secret back.
            return HTMLResponse(
                error_page("Could not verify the sign-in",
                           "Google answered, but the server could not read the reply.",
                           f"<code>{type(e).__name__}</code> - if this keeps happening, "
                           "the operator should check the OAuth client settings."),
                status_code=502)
        return HTMLResponse(return_page(request, account_id_for_sub(sub)))

    @app.get("/glogin/go")
    def glogin_go(request: Request, id: str = ""):
        """Park a chosen account id and hand back the return page. The dev page's
        buttons point here; only accepts the dev ids unless real Google is on (a raw
        id here would otherwise let anyone log in as any account)."""
        if not id or (not enabled() and not (DEV and id.startswith("google_dev"))):
            return HTMLResponse(
                error_page("Not allowed",
                           "That account cannot be signed into this way.",
                           "Only the dev test accounts work while Google is off."),
                status_code=403)
        return HTMLResponse(return_page(request, id))

    @app.get("/glogin/pending")
    def glogin_pending(request: Request):
        """The app's native poller reads the just-picked account id here (plain text,
        not AES - it's not a game-API route). Returned once, then cleared."""
        from fastapi.responses import PlainTextResponse
        acc = _get_and_clear_pending(_client_ip(request))
        return PlainTextResponse(acc)


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

    # Every page is one self-contained document: a player hits these over a tunnel,
    # on a phone, and a single missing asset is a blank screen with no way back.
    class MockRequest:
        client = None
        headers = {}
    mock_req = MockRequest()
    
    for html in (return_page(mock_req, "google_1"), dev_page(),
                 error_page("Nope", "detail", "hint")):
        assert html.startswith("<!doctype html>") and html.rstrip().endswith("</html>")
        assert "<style>" in html and "</div>" in html
        assert "http://" not in html and "https://" not in html, "an external asset crept in"
        assert "{" not in html.split("<style>")[0], "an unfilled format placeholder"

    # The return page must park the id for the poller AND offer the deep link, since
    # the client cannot read the URL it was sent back with.
    _get_and_clear_pending(_client_ip(mock_req))
    error_page("Nope", "detail")
    assert _get_and_clear_pending(_client_ip(mock_req)) == "", "error_page must not park an id"
    html = return_page(mock_req, "google_zz")
    assert _get_and_clear_pending(_client_ip(mock_req)) == "google_zz"
    assert f"{SCHEME}://auth" in html, "the return page lost its deep link"
    _get_and_clear_pending(_client_ip(mock_req))

    assert "google_devA" in dev_page() and "/glogin/go?id=" in dev_page()

    # --- the client-JSON loader -------------------------------------------------
    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp())

    good = tmp / "good.json"
    good.write_text(json.dumps({"web": {
        "client_id": "cid.apps.googleusercontent.com", "client_secret": "shh",
        "redirect_uris": ["http://localhost:8080/glogin/callback"]}}))
    assert load_client_file(good) == ("cid.apps.googleusercontent.com", "shh",
                                      "http://localhost:8080")

    # An Android/desktop client is the exact thing that cannot work here, so it must
    # read as unconfigured rather than half-load and fail at the token exchange.
    bad = tmp / "installed.json"
    bad.write_text(json.dumps({"installed": {"client_id": "x", "client_secret": "y"}}))
    assert load_client_file(bad) == ("", "", "")

    assert load_client_file(tmp / "nope.json") == ("", "", ""), "a missing file must be quiet"
    (tmp / "junk.json").write_text("{not json")
    assert load_client_file(tmp / "junk.json") == ("", "", "")

    # The redirect we send Google has to byte-match one it holds; deriving it from
    # the same file is the whole point, so a mismatched suffix must not be guessed at.
    odd = tmp / "odd.json"
    odd.write_text(json.dumps({"web": {"client_id": "c", "client_secret": "s",
                                       "redirect_uris": ["https://x.example/other"]}}))
    assert load_client_file(odd) == ("c", "s", "")

    print("google_login self-check ok")
