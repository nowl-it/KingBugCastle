"""Worker cycle + dashboard tests for the coupon bot.

Everything network-facing is monkeypatched: the cycle only ever touches the
Discord/coupon endpoints on the box, never in CI.
"""
import pathlib
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
    monkeypatch.setattr(config, "web_password", lambda: "hunter2")
    monkeypatch.setattr(config, "web_secret", lambda: "test-secret")
    monkeypatch.setattr(web, "_login_hits", {})
    return TestClient(web.app)


def _login(client, password="hunter2"):
    return client.post("/api/login", json={"password": password})


def test_api_requires_login(client):
    assert client.get("/api/state").status_code == 401
    assert client.get("/").status_code == 200, "login page itself is public"
    assert _login(client, "wrong").status_code == 401
    for _ in range(4):
        _login(client, "wrong")
    assert _login(client, "hunter2").status_code == 429, "lockout after 5 bad tries"
    web._login_hits.clear()          # simulate the 10-minute window elapsing
    assert _login(client).status_code == 200
    assert client.get("/api/state").status_code == 200


def test_account_probe_rejects_unknown_player_id(client, monkeypatch):
    _login(client)
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
    _login(client)
    assert client.post("/api/codes", json={"code": "kgcfest123"}).json()["code"] == "KGCFEST123"
    assert client.post("/api/codes", json={"code": "12345678"}).status_code == 400
    assert client.post("/api/codes", json={"code": "abc"}).status_code == 400


def test_run_endpoint_runs_once(client, monkeypatch):
    _login(client)
    calls = []
    monkeypatch.setattr(worker, "run_cycle", lambda **k: calls.append(k) or {"ok": 0})
    r = client.post("/api/run")
    assert r.status_code == 200 and r.json()["started"]
    for _ in range(50):
        if not web._run_flag["running"]:
            break
        time.sleep(0.05)
    assert len(calls) == 1
