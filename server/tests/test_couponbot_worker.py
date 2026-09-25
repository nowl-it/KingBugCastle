"""Worker cycle + dashboard tests for the coupon bot.

Everything network-facing is monkeypatched: the cycle only ever touches the
Discord/coupon endpoints on the box, never in CI.
"""
import json
import pathlib
import re
import sys
import time

_SERVER = pathlib.Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

import httpx
import pytest
from fastapi.testclient import TestClient

from couponbot import config, discord_feed, state, worker, web
from couponbot.coupon_client import Outcome, Result


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "DB_PATH", str(tmp_path / "coupons.db"))
    monkeypatch.setattr(state, "RAW_DIR", str(tmp_path / "raw"))
    state.init_db()
    return str(tmp_path / "coupons.db")


@pytest.fixture()
def quiet(monkeypatch):
    """No Discord reads, no notifications - unless a test overrides them."""
    monkeypatch.setattr(worker, "_notify", lambda text: None)
    monkeypatch.setattr(config, "read_channel", lambda: "")
    monkeypatch.delenv("COUPON_DISCORD_CHANNEL", raising=False)


def _msg(mid, content):
    return {"id": mid, "content": content, "embeds": []}


# --- discord feed -----------------------------------------------------------

def test_fetch_paginates_and_sorts(monkeypatch):
    pages = {
        "100": [{"id": "101", "content": "a", "embeds": []},
                {"id": "102", "content": "b", "embeds": []}],
        "102": [],
    }

    def handler(request):
        after = request.url.params.get("after")
        return httpx.Response(200, json=pages.get(after, []))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = discord_feed.fetch_new_messages("tok", "chan", "100", limit=2, client=client)
    assert [m["id"] for m in out] == ["101", "102"]
    assert discord_feed.message_text(
        {"content": "", "embeds": [{"description": "code: KGC77XQ2MM9"}]}
    ) == "code: KGC77XQ2MM9"


def test_fetch_maps_discord_errors(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"message": "401: Unauthorized"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(discord_feed.AuthError):
        discord_feed.fetch_new_messages("tok", "chan", client=client)

    def denied(request):
        return httpx.Response(403, json={"message": "Missing Access", "code": 50001})

    client = httpx.Client(transport=httpx.MockTransport(denied))
    with pytest.raises(discord_feed.MissingAccess):
        discord_feed.fetch_new_messages("tok", "chan", client=client)


# --- worker cycle -----------------------------------------------------------

def test_cycle_pulls_code_redeems_once_and_notifies(db, quiet, monkeypatch):
    monkeypatch.setattr(config, "read_channel", lambda: "chan123")
    monkeypatch.setattr(config, "bot_token", lambda: "tok")
    monkeypatch.setattr(discord_feed, "fetch_new_messages",
                        lambda *a, **k: [_msg("100", "coupon: `KGC77XQ2MM9`")])
    notices = []
    monkeypatch.setattr(worker, "_notify", notices.append)
    monkeypatch.setattr(state, "accounts",
                        lambda **k: [{"uid": "S6R83U", "enabled": 1}])
    monkeypatch.setattr(worker, "redeem",
                        lambda uid, code, **k: Outcome(Result.OK, "sent"))

    first = worker.run_cycle(lock=False)
    assert first["new_codes"] == 1 and first["found"] == ["KGC77XQ2MM9"]
    assert (first["attempted"], first["ok"]) == (1, 1)
    assert state.meta_get("discord_cursor") == "100"
    assert state.matrix() == {"S6R83U": {"KGC77XQ2MM9": "ok"}}
    assert len(notices) == 1 and "KGC77XQ2MM9" in notices[0]

    second = worker.run_cycle(lock=False)
    assert (second["attempted"], second["ok"]) == (0, 0)
    assert len(notices) == 1, "quiet cycles must not spam Discord"


def test_unknown_code_closes_for_every_account(db, quiet, monkeypatch):
    state.add_account("S6R83U")
    state.add_account("SECOND01")
    state.add_code("BOGUS0001", "manual")
    calls = []
    monkeypatch.setattr(
        worker, "redeem",
        lambda uid, code, **k: (calls.append((uid, code)),
                                Outcome(Result.NO_COUPON, "This coupon does not exist."))[1])

    out = worker.run_cycle(lock=False)
    assert out["attempted"] == 1, "second account must not waste a request"
    assert calls == [("S6R83U", "BOGUS0001")]
    assert state.codes()[0]["status"] == "invalid"


def test_expired_code_closes_too(db, quiet, monkeypatch):
    state.add_account("S6R83U")
    state.add_code("OLD123456", "manual")
    monkeypatch.setattr(worker, "redeem",
                        lambda uid, code, **k: Outcome(Result.EXPIRED, "expired"))
    worker.run_cycle(lock=False)
    assert state.codes()[0]["status"] == "expired"


def test_transport_error_is_retried_next_cycle(db, quiet, monkeypatch):
    state.add_account("S6R83U")
    state.add_code("KGCFEST123", "manual")
    monkeypatch.setattr(worker, "redeem", lambda uid, code, **k: Outcome(Result.ERROR, "HTTP 500"))

    out = worker.run_cycle(lock=False)
    assert out["errors"] == 1
    assert state.needs_attempt("S6R83U", "KGCFEST123"), "not recorded -> retried later"


def test_second_cycle_wins_the_lock(db, quiet, monkeypatch):
    monkeypatch.setattr(worker, "redeem",
                        lambda uid, code, **k: Outcome(Result.OK, "sent"))
    held = worker._Lock(blocking=True)
    assert held
    try:
        assert worker.run_cycle(lock=True).get("busy") is True
    finally:
        held.__exit__(None, None, None)


def test_blocked_reader_degrades_to_manual_once(db, quiet, monkeypatch):
    monkeypatch.setattr(config, "read_channel", lambda: "chan123")
    monkeypatch.setattr(config, "bot_token", lambda: "tok")

    def boom(*a, **k):
        raise discord_feed.MissingAccess("missing access to channel")

    monkeypatch.setattr(discord_feed, "fetch_new_messages", boom)
    notices = []
    monkeypatch.setattr(worker, "_notify", notices.append)

    assert worker.run_cycle(lock=False)["discord"].startswith("manual:")
    assert state.meta_get("discord_mode") == "manual"
    assert len(notices) == 1
    worker.run_cycle(lock=False)
    assert len(notices) == 1, "already-degraded mode must not re-notify"


# --- dashboard --------------------------------------------------------------

@pytest.fixture()
def client(db, monkeypatch):
    # No auth exists any more (the page is public), and the write throttle is
    # per client IP - so every test starts from a clean slate.
    web._write_hits.clear()
    return TestClient(web.app)


def test_api_is_public_no_login_anywhere(client):
    """Operator decision: anyone adds their own ID, nobody logs in."""
    assert client.get("/").status_code == 200
    assert client.get("/api/state").status_code == 200      # no cookie, no password
    assert client.post("/api/login", json={"password": "x"}).status_code == 404
    assert client.post("/api/logout").status_code == 404


def test_nothing_can_be_deleted_through_the_api(client, monkeypatch):
    monkeypatch.setattr(web, "redeem",
                        lambda *a, **k: Outcome(Result.NO_COUPON, "This coupon does not exist."))
    assert client.post("/api/accounts", json={"uid": "S6R83U", "label": "main"}).status_code == 200
    assert client.post("/api/codes", json={"code": "KGCFEST123"}).status_code == 200

    assert client.delete("/api/accounts/S6R83U").status_code == 404
    assert client.post("/api/accounts/S6R83U/enable").status_code == 404
    assert client.delete("/api/codes/KGCFEST123").status_code == 404

    payload = client.get("/api/state").json()
    assert [a["uid"] for a in payload["accounts"]] == ["S6R83U"]
    assert [c["code"] for c in payload["codes"]] == ["KGCFEST123"]


def test_state_lists_every_id_and_every_code(client, monkeypatch):
    monkeypatch.setattr(web, "redeem",
                        lambda *a, **k: Outcome(Result.NO_COUPON, "This coupon does not exist."))
    for uid in ("AAAA11", "BBBB22"):
        assert client.post("/api/accounts", json={"uid": uid}).status_code == 200
    for i in range(15):
        assert client.post("/api/codes", json={"code": f"KGC{i:02d}TEST"}).status_code == 200

    payload = client.get("/api/state").json()
    assert [a["uid"] for a in payload["accounts"]] == ["AAAA11", "BBBB22"]
    assert len(payload["codes"]) == 15, "the old UI capped the list at 12"
    # an anonymous GET really does receive the ID list
    assert "AAAA11" in client.get("/api/state").text


def test_write_throttle_stops_probe_spam(client, monkeypatch):
    """The add-account probe costs one real request to the official site."""
    monkeypatch.setitem(web.WRITE_LIMITS, "account", (2, 60))
    monkeypatch.setattr(web, "redeem",
                        lambda *a, **k: Outcome(Result.NO_COUPON, "This coupon does not exist."))
    for i in range(2):
        assert client.post("/api/accounts", json={"uid": f"AAAA{i}"}).status_code == 200
    assert client.post("/api/accounts", json={"uid": "AAAA2"}).status_code == 429


def test_account_probe_rejects_unknown_player_id(client, monkeypatch):
    monkeypatch.setattr(web, "redeem",
                        lambda *a, **k: Outcome(Result.NO_PID, "This Player-ID does not exist."))
    r = client.post("/api/accounts", json={"uid": "NOPE12", "label": "x"})
    assert r.status_code == 422

    monkeypatch.setattr(web, "redeem",
                        lambda *a, **k: Outcome(Result.NO_COUPON, "This coupon does not exist."))
    r = client.post("/api/accounts", json={"uid": "S6R83U", "label": "main"})
    assert r.status_code == 200, r.text
    assert [a["uid"] for a in client.get("/api/state").json()["accounts"]] == ["S6R83U"]
    assert client.post("/api/accounts", json={"uid": "S6R83U"}).status_code == 409


def test_code_validation(client):
    assert client.post("/api/codes", json={"code": "kgcfest123"}).json()["code"] == "KGCFEST123"
    assert client.post("/api/codes", json={"code": "12345678"}).status_code == 400
    assert client.post("/api/codes", json={"code": "abc"}).status_code == 400


def test_run_endpoint_runs_once(client, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "run_cycle", lambda **k: calls.append(k) or {"ok": 0})
    r = client.post("/api/run")
    assert r.status_code == 200 and r.json()["started"]
    for _ in range(50):
        if not web._run_flag["running"]:
            break
        time.sleep(0.05)
    assert len(calls) == 1


_STATIC = pathlib.Path(__file__).resolve().parent.parent / "couponbot" / "static"


def _i18n() -> dict:
    """static/i18n.js is `const KGC_I18N = <JSON>;` on purpose so it parses here."""
    txt = (_STATIC / "i18n.js").read_text(encoding="utf-8")
    blob = txt[txt.index("KGC_I18N =") + len("KGC_I18N ="):]
    return json.loads(blob[blob.index("{"):blob.rindex("}") + 1])


def test_every_string_the_page_uses_is_translated_in_both_languages():
    """A key missing from one language would silently fall back to the other."""
    dicts = _i18n()
    assert set(dicts) == {"vi", "en"}
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    js = (_STATIC / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n(?:-html|-ph)?="([^"]+)"', html))
    used |= set(re.findall(r'\bt\(\s*"([a-z0-9_]+)"', js))
    assert used, "no keys matched - the i18n markers in the page rotted"
    vi, en = set(dicts["vi"]), set(dicts["en"])
    assert vi == en, f"the two languages drifted apart: {sorted(vi ^ en)}"
    assert not (used - vi), f"untranslated key(s): {sorted(used - vi)}"


def test_every_server_error_code_is_translated_too(client):
    """The English page must not end up showing a Vietnamese API sentence."""
    dicts = _i18n()
    src = pathlib.Path(web.__file__).read_text(encoding="utf-8")
    server_codes = set(re.findall(r'code="([a-z_]+)"', src))
    assert server_codes, "no error codes found in web.py - marker rotted"
    assert server_codes <= set(dicts["vi"]), sorted(server_codes - set(dicts["vi"]))
    assert server_codes <= set(dicts["en"]), sorted(server_codes - set(dicts["en"]))
    # ...and the field really is on the wire ("ABCD1" is too short, so the
    # length check fires before the letters+digits one)
    r = client.post("/api/codes", json={"code": "ABCD1"})
    assert r.status_code == 400 and r.json()["code"] == "code_len"
    assert r.json()["error"], "the Vietnamese human message stays for logs/curl"


def test_first_request_on_a_db_that_does_not_exist_yet(tmp_path, monkeypatch):
    """Real curl on a fresh box gave `no such table: accounts` -> 500: the test
    fixture always inits the DB first, so only a first-ever request could see it."""
    monkeypatch.setattr(state, "DB_PATH", str(tmp_path / "fresh.db"))
    web._write_hits.clear()
    fresh = TestClient(web.app)
    assert fresh.get("/api/state").status_code == 200
    payload = fresh.get("/api/state").json()
    assert payload["accounts"] == [] and payload["codes"] == []
    assert fresh.post("/api/codes", json={"code": "KGCFRESH01"}).status_code == 200


def test_cli_accepts_the_flags_the_systemd_unit_passes(db, quiet, capsys):
    """`ExecStart=... --once` failed once with argparse exit 2 - keep it green."""
    assert worker.main(["--once", "--dry"]) == 0
    assert "dry" in capsys.readouterr().out
    assert worker.main(["--dry", "--no-lock", "--code", "KGCFEST123"]) == 0
    assert state.codes()[0]["code"] == "KGCFEST123"
