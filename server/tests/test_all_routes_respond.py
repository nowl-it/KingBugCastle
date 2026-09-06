"""Every route the client can call must answer, on a body it did not expect.

route_coverage grades whether a path has a handler; it says nothing about whether
that handler survives being called. This walks the client's own route list and
posts an empty body to each - which is exactly what a handler that reads
`body["x"]` instead of `body.get("x")` dies on, and the client does send partial
bodies.

That is not hypothetical: /card/upgradePotentialTier answered 500 for a hero the
save did not have, because its fallback card had no potentialTier key.
"""
import json, sys, tempfile
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import route_coverage
import server
from fastapi.testclient import TestClient

# TestClient's default peer is the literal "testclient", which is not loopback -
# the admin guard would reject every request and the failures would look like
# handler crashes.
client = TestClient(server.app, client=("127.0.0.1", 50000))


def _decode(raw):
    body = server.aes_decrypt(raw)
    return body if isinstance(body, dict) else json.loads(body)


def check_every_client_route_answers_an_empty_body():
    paths = [p for p in sorted(route_coverage.client_paths())
             if not p.startswith("/patch") and not p.startswith("/admin")]
    bad = []
    for p in paths:
        try:
            request_body = b""
            if p == "/colosseum/join-custom-match":
                created = client.post("/colosseum/create-custom-match", content=b"")
                lobby_id = _decode(created.content).get("lobbyId")
                request_body = server.aes_encrypt({"matchId": lobby_id})
            r = client.post(p, content=request_body)
            if r.status_code != 200:
                bad.append((p, f"HTTP {r.status_code}"))
                continue
            body = _decode(r.content)
            if body.get("code") != 200:
                bad.append((p, str(body)[:80]))
        except Exception as e:                      # noqa: BLE001 - report, don't stop
            bad.append((p, repr(e)[:80]))
    assert not bad, "routes that did not answer:\n" + \
        "\n".join(f"  {p}: {why}" for p, why in bad[:25])
    print(f"ok: {len(paths)} client routes all answered a minimal body")


def check_the_route_list_is_the_clients():
    """The inventory has to come from the deployed binary, or this test grades us
    against our own list of routes and always passes."""
    paths = route_coverage.client_paths()
    assert len(paths) > 300, f"only {len(paths)} routes read out of the binary"
    assert "/player" in paths and "/colosseum" in paths
    print(f"ok: {len(paths)} routes read from the v171 binary's string table")


def check_coverage_holds():
    r = route_coverage.report()
    assert not r["bare"], f"routes back on the generic model: {sorted(r['bare'])[:10]}"
    assert not r["modelled_only"], \
        f"routes back to an empty model: {sorted(r['modelled_only'])[:10]}"
    print(f"ok: {len(r['handled'])} handled, 0 model only, 0 bare")


if __name__ == "__main__":
    check_the_route_list_is_the_clients()
    check_coverage_holds()
    check_every_client_route_answers_an_empty_body()
    print("\nall route-response checks passed")
