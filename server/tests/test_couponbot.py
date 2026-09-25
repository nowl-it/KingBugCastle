"""Tests for the coupon auto-redeem core: site parsing, code extraction, store.

Network-free: the two live fixtures were captured by 00-recon.md against the
real site; the other result pages are synthesised from the same template with
the exact English strings the site serves for `lang=en_us`.
"""
import pathlib
import sys
import time

_SERVER = pathlib.Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

import httpx

# Package import, not bare `import state`/`codes`: `server/state.py` is a
# top-level module the emulator already owns, and pytest shares one sys.modules
# across the whole suite.
from couponbot import codes, coupon_client, state
from couponbot.coupon_client import Result, parse_page, redeem, Limiter

FIXTURES = _SERVER / "tests" / "fixtures" / "coupon"

# Same skeleton as the live pages, only the <p> differs.
_PAGE = """<!doctype html><html><body>
<h1 class="display-4 fw-bold lh-1 mb-2">{h1}</h1>
<p class="col-lg-10 fs-4">{body}</p>
</body></html>"""


def page(body, h1="Failed to enter coupon"):
    return _PAGE.format(h1=h1, body=body)


def test_live_fixtures():
    assert parse_page((FIXTURES / "nopid.html").read_text())[0] is Result.NO_PID
    assert parse_page((FIXTURES / "nocoupon.html").read_text())[0] is Result.NO_COUPON


def test_all_site_messages_map_to_results():
    cases = [
        (page("Rewards have been sent to your inbox. Please log in to check.",
               h1="Success!"), Result.OK),
        (page("This Player-ID does not exist. Please check and try again."),
         Result.NO_PID),
        (page("This coupon does not exist."), Result.NO_COUPON),
        (page("This coupon number is invalid or has already been used."),
         Result.USED_OR_INVALID),
        (page("This coupon has expired."), Result.EXPIRED),
        (page("The coupon cannot be entered currently. Please try again later."),
         Result.NOT_AVAILABLE),
        (page("The usage limit has been reached."), Result.LIMIT_REACHED),
    ]
    for html, want in cases:
        got, msg = parse_page(html)
        assert got is want, f"{want} -> {got} ({msg})"
        assert msg, "message text must survive for the dashboard"


def test_unrecognised_page_is_error_and_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RAW_DIR", str(tmp_path))

    def handler(request):
        return httpx.Response(200, text="<html><body>maintenance</body></html>")

    client = httpx.Client(base_url=coupon_client.SITE,
                          transport=httpx.MockTransport(handler))
    out = redeem("S6R83U", "CODE1234", client=client, limiter=Limiter(0))
    assert out.result is Result.ERROR
    saved = list(tmp_path.glob("*.html"))
    assert len(saved) == 1 and "S6R83U" in saved[0].name


def test_redeem_posts_expected_body_and_reads_rate_limit():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = dict(x.split("=") for x in request.content.decode().split("&"))
        return httpx.Response(
            200,
            text=page("Rewards have been sent to your inbox. Please log in to check.",
                      h1="Success!"),
            headers={"X-Rate-Limit-Remaining": "297"},
        )

    client = httpx.Client(base_url=coupon_client.SITE,
                          transport=httpx.MockTransport(handler))
    out = redeem("S6R83U", "CODE1234", client=client, limiter=Limiter(0))
    assert out.result is Result.OK and out.remaining == 297
    assert seen["url"].endswith("/submitCoupon")
    assert seen["body"] == {"uid": "S6R83U", "code": "CODE1234", "lang": "en_us"}
    assert coupon_client.RATE["remaining"] == 297


def test_limiter_enforces_gap():
    lim = Limiter(0.15)
    t0 = time.monotonic()
    for _ in range(3):
        lim.wait()
    assert time.monotonic() - t0 >= 0.30


def _msgs(texts):
    return [(t, codes.extract(t)) for t in texts]


def test_extract_code_blocks_and_context():
    assert codes.extract("```KGCFESTIVAL2026```") == ["KGCFESTIVAL2026"]
    assert codes.extract("`kgcfestival2026`") == ["KGCFESTIVAL2026"]
    assert codes.extract("Here is your coupon: KGC77XQ2MM9") == ["KGC77XQ2MM9"]
    assert codes.extract("COUPON CODE: SEASON-73-NOW") == ["SEASON-73-NOW"]
    # dedupe across span + line
    assert codes.extract("coupon: `KGCFESTIVAL2026` (repeat KGCFESTIVAL2026)") == \
        ["KGCFESTIVAL2026"]


def test_extract_rejects_noise():
    assert codes.extract("https://discord.com/channels/1/2/3") == []
    assert codes.extract("check https://kgc.gg/coupon KGCFESTIVAL2026") == []
    assert codes.extract("coupon deadbeefdeadbeefdeadbeefdeadbeef") == []  # md5
    assert codes.extract("coupon SUPERLONGCODE1234567890ABCDEFG") == []  # >20 chars
    assert codes.extract("ANNOUNCEMENT ANNOUNCEMENT2") == []
    assert codes.extract("Season 73 Harvest Moon Festival") == []
    assert codes.extract("no codes here at all") == []
    # needs a letter AND a digit, >=8 alphanumerics
    assert codes.extract("coupon: FREEGEMS") == []


def test_store_attempt_once_and_code_status(tmp_path):
    db = str(tmp_path / "t.db")
    state.init_db(db)
    assert state.add_account("S6R83U", "main", path=db)
    assert not state.add_account("S6R83U", "again", path=db)
    assert state.add_code("KGCFESTIVAL2026", "discord:123", path=db)
    assert not state.add_code("KGCFESTIVAL2026", "discord:123", path=db)

    assert state.needs_attempt("S6R83U", "KGCFESTIVAL2026", path=db)
    state.record_redemption("S6R83U", "KGCFESTIVAL2026", "ok", "sent", path=db)
    assert not state.needs_attempt("S6R83U", "KGCFESTIVAL2026", path=db)
    # first result wins, later attempts cannot overwrite it
    assert not state.record_redemption("S6R83U", "KGCFESTIVAL2026", "error", "", path=db)
    assert state.redemption("S6R83U", "KGCFESTIVAL2026", path=db)["status"] == "ok"

    # a code that does not exist closes for everybody; others stay open
    state.add_code("BOGUS0001", "manual", path=db)
    state.set_code_status("BOGUS0001", "invalid", path=db)
    open_ids = [c["code"] for c in state.open_codes(path=db)]
    assert open_ids == ["KGCFESTIVAL2026"]

    assert state.matrix(path=db) == {"S6R83U": {"KGCFESTIVAL2026": "ok"}}

    run = state.start_run(path=db)
    state.finish_run(run, found=1, new=1, attempted=1, ok=1, path=db)
    assert state.last_run(path=db)["ok"] == 1

    state.meta_set("discord_cursor", "12345", path=db)
    assert state.meta_get("discord_cursor", path=db) == "12345"


def test_accounts_enabled_toggle(tmp_path):
    db = str(tmp_path / "t.db")
    state.init_db(db)
    state.add_account("S6R83U", "main", path=db)
    state.add_account("SECOND01", "alt", path=db)
    assert len(state.accounts(path=db)) == 2
    state.set_account_enabled("SECOND01", False, path=db)
    assert [a["uid"] for a in state.accounts(path=db)] == ["S6R83U"]
    assert state.account("SECOND01", path=db)["enabled"] == 0
