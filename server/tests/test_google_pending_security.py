"""A Google login handoff must be safely consumable only by its client."""
import asyncio
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI

_SERVER = Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

import google_login
import routes.player_routes as player_routes
import security
from routes import direct_routes


def test_pending_google_account_cannot_be_consumed_by_a_different_address(monkeypatch, tmp_path):
    monkeypatch.setattr(google_login, "_pending_file",
                        lambda ip: tmp_path / f"pending-{ip}")
    google_login._set_pending("198.51.100.10", "google_victim")

    assert google_login._get_and_clear_pending("203.0.113.20") == ""
    assert google_login._get_and_clear_pending("198.51.100.10") == "google_victim"
    assert google_login._get_and_clear_pending("198.51.100.10") == ""


def test_pending_google_account_is_published_and_consumed_once(monkeypatch, tmp_path):
    target = tmp_path / "pending-198.51.100.10"
    monkeypatch.setattr(google_login, "_pending_file", lambda _ip: target)
    real_replace = google_login.os.replace
    published = []

    def observe_publish(source, destination):
        if Path(destination) == target:
            assert Path(source).read_text(encoding="utf-8") == "google_atomic"
            published.append(True)
        return real_replace(source, destination)

    monkeypatch.setattr(google_login.os, "replace", observe_publish)
    google_login._set_pending("198.51.100.10", "google_atomic")
    assert published == [True]

    barrier = threading.Barrier(2)

    def race_replace(source, destination):
        if Path(source) == target:
            barrier.wait(timeout=2)
        return real_replace(source, destination)

    monkeypatch.setattr(google_login.os, "replace", race_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: google_login._get_and_clear_pending("198.51.100.10"), range(2)))
    assert sorted(values) == ["", "google_atomic"]
    assert not list(tmp_path.glob("pending-*"))
    assert not list(tmp_path.glob(".pending-*"))


def test_native_google_auth_grant_is_address_bound_fresh_and_single_use(monkeypatch, tmp_path):
    monkeypatch.setattr(
        google_login, "_native_auth_grant_file",
        lambda ip, account: tmp_path / f"grant-{ip}-{account}")
    google_login._grant_native_auth("198.51.100.10", "google_42", now=100)

    assert not google_login.consume_native_auth_grant("198.51.100.11", "google_42", now=101)
    assert not google_login.consume_native_auth_grant("198.51.100.10", "google_other", now=101)
    assert google_login.consume_native_auth_grant("198.51.100.10", "google_42", now=101)
    assert not google_login.consume_native_auth_grant("198.51.100.10", "google_42", now=101)

    google_login._grant_native_auth("198.51.100.10", "google_42", now=100)
    assert not google_login.consume_native_auth_grant(
        "198.51.100.10", "google_42", now=100 + google_login.NATIVE_AUTH_GRANT_TTL + 1)


def test_native_auth_route_requires_the_google_handoff_grant(monkeypatch, tmp_path):
    class Request:
        headers = {"host": "kgc.test"}
        query_params = {"id": "google_victim"}
        client = SimpleNamespace(host="198.51.100.10")

    original_srv = direct_routes.srv
    app = FastAPI()
    direct_routes.register(app, SimpleNamespace(
        aes_encrypt=lambda payload: json.dumps(payload).encode("utf-8")))
    endpoint = next(route.endpoint for route in app.routes if route.path == "/auth")
    minted = []
    monkeypatch.setattr(player_routes, "mint_session_token",
                        lambda login_id: minted.append(login_id) or "session-token")
    monkeypatch.setattr(
        google_login, "_native_auth_grant_file",
        lambda ip, account: tmp_path / f"grant-{ip}-{account}")
    try:
        denied = asyncio.run(endpoint(Request()))
        assert json.loads(denied.body) == {
            "code": 200, "msg": "Google sign-in was not verified", "success": False}
        assert minted == []

        google_login._grant_native_auth("198.51.100.10", "google_victim")
        accepted = asyncio.run(endpoint(Request()))
        assert json.loads(accepted.body)["success"] is True
        assert minted == ["google_victim"]
    finally:
        direct_routes.srv = original_srv


class _Request:
    class client:
        host = "198.51.100.10"

    headers = {"x-forwarded-for": "203.0.113.20"}


def test_google_handoff_uses_the_shared_proxy_trust_policy(monkeypatch):
    monkeypatch.setattr(security, "TRUST_PROXY", False)
    assert google_login._client_ip(_Request()) == "198.51.100.10"

    monkeypatch.setattr(security, "TRUST_PROXY", True)
    assert google_login._client_ip(_Request()) == "203.0.113.20"
