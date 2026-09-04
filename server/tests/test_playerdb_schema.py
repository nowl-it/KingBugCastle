"""Schema migrations, derived projections, and the legacy-JSON retirement.

The derived tables are a cache of the JSON blob. If they are ever read for game
logic, or if they silently stop updating, both failures look like "the dashboard
shows stale numbers" rather than an error - hence these.
"""
import asyncio, json, sys, tempfile, pathlib, sqlite3, types

_SERVER = pathlib.Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)
import playerdb
import routes.player_routes as player_routes


def _fresh_db():
    playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    playerdb.init()


def test_fresh_db_is_at_head_and_init_is_idempotent():
    _fresh_db()
    with playerdb._conn() as c:
        assert playerdb._schema_version(c) == playerdb.SCHEMA_VERSION
    assert playerdb.init() == playerdb.SCHEMA_VERSION


def test_migration_from_v1_backs_up_and_upgrades():
    """An old database - only the v1 tables, no schema_version - must survive."""
    d = pathlib.Path(tempfile.mkdtemp())
    playerdb.DB_PATH = d / "old.db"
    raw = sqlite3.connect(playerdb.DB_PATH)
    raw.execute("CREATE TABLE players (uid TEXT PRIMARY KEY, data TEXT NOT NULL, updated REAL NOT NULL)")
    raw.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    raw.execute("CREATE TABLE sessions (token TEXT PRIMARY KEY, uid TEXT NOT NULL, created REAL NOT NULL)")
    raw.execute("CREATE TABLE accounts (login_id TEXT PRIMARY KEY, uid TEXT NOT NULL)")
    raw.execute("INSERT INTO players VALUES (?,?,?)",
                ("old-1", json.dumps({"uid": "old-1", "name": "Ancient", "gold": 42,
                                      "inventory": {"itemIds": [7], "counts": [3]}}), 0.0))
    raw.commit(); raw.close()

    assert playerdb.init() == playerdb.SCHEMA_VERSION
    assert playerdb.load("old-1")["gold"] == 42, "migration lost the save"
    with playerdb._conn() as c:
        assert c.execute("SELECT gold FROM players WHERE uid='old-1'").fetchone()[0] == 42
        assert c.execute("SELECT count FROM player_items WHERE uid='old-1'").fetchone()[0] == 3
    backups = list((d / "backups").glob("players-*-v1.db"))
    assert backups, "migrating an existing DB must leave a backup behind"


def test_derived_tables_are_a_cache_not_a_source():
    """Corrupt the projection; the save must be unaffected and rebuildable."""
    _fresh_db()
    playerdb.save("p1", {"uid": "p1", "gold": 100, "inventory": {"itemIds": [5], "counts": [9]}})
    with playerdb._conn() as c:
        c.execute("UPDATE player_items SET count=0 WHERE uid='p1'")
        c.execute("UPDATE players SET gold=-1 WHERE uid='p1'")
    assert playerdb.load("p1")["gold"] == 100, "a derived column changed the actual save"
    playerdb.reindex_all()
    with playerdb._conn() as c:
        assert c.execute("SELECT gold FROM players WHERE uid='p1'").fetchone()[0] == 100
        assert c.execute("SELECT count FROM player_items WHERE uid='p1'").fetchone()[0] == 9


def test_load_repairs_malformed_cards_and_decks_before_routes_use_them():
    """A bad raw-save edit must not make the account unloadable forever."""
    _fresh_db()
    playerdb.save("broken", {
        "uid": "broken",
        "cards": {
            "oops": {"unitId": 10000, "level": 1},
            "10000": {"level": "7"},
            "10010": "not-a-card",
        },
        "decks": [
            {"deck": [10000, "oops", 42110, 0], "potential": ["2", -1, None],
             "firstComerIndex": "3"},
            "not-a-deck",
        ],
    })

    state = playerdb.load("broken")

    assert state["cards"] == {"10000": {"unitId": 10000, "level": 7}}
    assert state["decks"] == [{
        "deck": [10000, 10000, 10000, 0, 0, 0],
        "potential": [2, 0, 0, 0, 0, 0],
        "firstComerIndex": 3,
    }]


def test_identity_lookups_reject_non_string_values_before_sqlite_binding():
    _fresh_db()
    playerdb.save("p", {"uid": "p"})
    playerdb.bind_session("valid-token", "p")
    playerdb.bind_login("valid-login", "p")

    for malformed in ({"token": "x"}, ["x"], 1, True, b"x"):
        assert playerdb.uid_for_token(malformed) is None
        assert playerdb.uid_for_login(malformed) is None

    assert playerdb.uid_for_token("valid-token") == "p"
    assert playerdb.uid_for_login("valid-login") == "p"


def test_login_identity_is_a_bounded_string_before_persistence():
    _fresh_db()
    playerdb.save("p", {"uid": "p"})
    too_long = "x" * (playerdb.MAX_LOGIN_ID_LENGTH + 1)
    for malformed in ("", too_long, {"id": "x"}, ["x"], 1, True):
        assert not playerdb.valid_login_id(malformed)
        try:
            playerdb.bind_login(malformed, "p")
        except ValueError:
            pass
        else:
            raise AssertionError(f"malformed login id was persisted: {malformed!r}")
    assert playerdb.valid_login_id("Guest_ABC123")
    playerdb.bind_login("Guest_ABC123", "p")
    assert playerdb.uid_for_login("Guest_ABC123") == "p"


def test_auth_rejects_a_malformed_new_identity_but_allows_session_refresh():
    _fresh_db()
    playerdb.save("p", {"uid": "p"})
    playerdb.bind_session("refresh-token", "p")
    malformed = {"id": "not-a-client-string"}
    assert player_routes._uid_for_login(malformed, None) is None
    assert player_routes._uid_for_login("x" * 257, "refresh-token") == "p"


def test_backfill_repairs_malformed_account_ids_as_missing_identity():
    _fresh_db()
    playerdb.save("valid", {"uid": "valid", "accountId": 7})
    playerdb.save("malformed", {"uid": "malformed", "accountId": "not-an-id"})
    playerdb.save("missing", {"uid": "missing"})

    assert playerdb.backfill_account_ids() == 2
    ids = [playerdb.load(uid)["accountId"] for uid in ("valid", "malformed", "missing")]
    assert ids[0] == 7
    assert all(isinstance(account_id, int) and account_id > 0 for account_id in ids)
    assert len(set(ids)) == len(ids)


def test_dashboard_raw_save_preserves_the_player_account_identity():
    _fresh_db()
    playerdb.save("p", {"uid": "p", "accountId": 42, "name": "Before"})
    import dashboard

    asyncio.run(dashboard.api_player_raw_save("p", {
        "uid": "someone-else",
        "accountId": 999,
        "name": "After",
    }))

    state = playerdb.load("p")
    assert state["uid"] == "p"
    assert state["accountId"] == 42
    assert state["name"] == "After"


def test_dashboard_legacy_max_macro_builds_artifacts_and_treasures(monkeypatch):
    _fresh_db()
    playerdb.save("p", {"uid": "p", "accountId": 42})
    import dashboard
    import gamedata
    import routes.artifact_routes as artifact_routes

    # dashboard imports the live server lazily inside the macro.  Keep this
    # unit test independent from the whole ASGI module by supplying only the
    # domain collaborators this branch needs.
    fake_server = types.SimpleNamespace(
        XML_DIR=pathlib.Path(gamedata.XML_DIR),
        ALL_TREASURE_IDS=[50001, 50002],
        make_max_artifact=lambda index, artifact_id: {
            "id": index, "artifactId": artifact_id, "count": 99999,
        },
    )
    monkeypatch.setitem(sys.modules, "server", fake_server)
    monkeypatch.setattr(artifact_routes, "make_treasure", lambda index, treasure_id: {
        "id": index, "treasureId": treasure_id,
    })

    result = asyncio.run(dashboard.api_player_macro("p", {"macro": "legacy_max"}))
    state = playerdb.load("p")

    assert result["ok"] is True
    assert state["artifacts"], "legacy_max omitted all artifacts"
    assert state["treasures"], "legacy_max omitted all treasures"
    assert all(a["count"] == 99999 for a in state["artifacts"])
    assert all(t["level"] == 30 and t["overcome"] == 10 for t in state["treasures"])


def test_legacy_json_is_retired_so_it_cannot_be_reimported():
    """The bug this fixes: state/player.json stayed on disk next to its own backup,
    so every later empty database re-imported it and resurrected deleted players."""
    d = pathlib.Path(tempfile.mkdtemp())
    playerdb.DB_PATH = d / "state" / "players.db"
    state = d / "state"
    (state / "players").mkdir(parents=True)
    (state / "player.json").write_text(json.dumps({"uid": "legacy-a", "gold": 5}))
    (state / "players" / "legacy-b.json").write_text(json.dumps({"uid": "legacy-b", "gold": 6}))

    assert playerdb.migrate_from_json(state) == 2
    assert playerdb.count() == 2
    assert not (state / "player.json").exists(), "legacy file left in place"
    assert list((state / "pre-sqlite-backup").glob("*.json")), "legacy file was deleted, not moved"

    # A brand new database over the same state dir must NOT resurrect them.
    playerdb.DB_PATH = state / "second.db"
    playerdb.init()
    assert playerdb.migrate_from_json(state) == 0
    assert playerdb.count() == 0, "deleted players came back from the legacy JSON"


def test_periodic_backup_fires_once_per_window():
    """Both uvicorn processes run the same timer. Without a shared due-check they
    each take a backup seconds apart, and the pair evicts two genuinely older ones."""
    d = pathlib.Path(tempfile.mkdtemp())
    playerdb.DB_PATH = d / "state" / "b.db"
    playerdb.init()
    playerdb.save("a", {"uid": "a", "gold": 1})

    t = 1_000_000.0
    assert playerdb.backup_if_due(3600, now=t), "first run took no backup"
    assert playerdb.backup_if_due(3600, now=t + 30) is None, "second process backed up too"
    assert playerdb.backup_if_due(3600, now=t + 3601), "the next window never opened"
    assert playerdb.backup_if_due(0) is None, "interval 0 must disable it"


def test_backup_retention_keeps_the_newest():
    """Retention sorted by filename, and an older naming scheme put the tag first -
    so "players-manual-2026...db" ranked after every timestamp-first name and the
    prune deleted the newest backups while keeping the oldest."""
    d = pathlib.Path(tempfile.mkdtemp())
    playerdb.DB_PATH = d / "state" / "r.db"
    playerdb.init()
    playerdb.save("a", {"uid": "a"})
    bdir = d / "state" / "backups"
    bdir.mkdir(parents=True, exist_ok=True)

    import os, time as _t
    legacy = bdir / "players-manual-20200101-000000.db"     # sorts LAST by name
    legacy.write_bytes(b"old")
    os.utime(legacy, (0, 0))                                # but is the oldest by far
    for i in range(playerdb.BACKUP_KEEP):
        f = bdir / f"players-2026010{i % 9}-00000{i}-auto.db"
        f.write_bytes(b"x")
        os.utime(f, (_t.time() - 100 + i, _t.time() - 100 + i))

    playerdb._backup("newest")
    left = {p.name for p in bdir.glob("*.db")}
    assert legacy.name not in left, "kept the oldest backup and dropped a newer one"
    assert any(n.endswith("-newest.db") for n in left), "deleted the backup it just took"
    assert len(left) == playerdb.BACKUP_KEEP, f"kept {len(left)}, want {playerdb.BACKUP_KEEP}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("\nall playerdb schema checks passed")
