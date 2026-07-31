"""SQLite-backed player state.

Replaces state/player.json + state/players/*.json. Why: the JSON files were read
and written by BOTH uvicorn processes (:8080 and :8443) with only a
threading.Lock guarding them, which locks nothing across processes - so a
concurrent write lost the other side's update or left a half-written file.
SQLite in WAL mode gives cross-process locking and atomic commits for free, and
one row per uid is what multi-player needs anyway.

**The JSON blob stays the source of truth.** Every handler works the same way -
`load_state()` -> mutate a dict -> `save_state()` - so normalising the save into
real columns would mean rewriting all ~280 of them. Instead `save()` also writes
*derived* rows (`players.name/gold/cash/level`, `player_items`, `player_cards`)
straight off the blob. They are indexed and queryable like any table, they can be
rebuilt from the blob at any time (`reindex_all()`), and nothing reads them for
game logic - so a bug there can never corrupt a save.

Schema changes go through `MIGRATIONS`: `init()` compares `meta.schema_version`,
takes a file backup, and applies what is missing. Never edit an applied migration.
"""
import contextlib, fcntl, json, os, shutil, sqlite3, sys, time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "state" / "players.db"
BACKUP_KEEP = 10          # newest N pre-migration backups to keep

# PostgreSQL instead of SQLite: KGC_DB_URL=postgresql://user:pw@host/db
# (needs `pip install "psycopg[binary]"`). SQLite stays the default - it needs no
# service, and one game client plus one operator is not a concurrency problem.
# Postgres is worth it when several server processes on DIFFERENT machines share
# one save store, which is the one thing SQLite-over-a-file cannot do safely.
DB_URL = os.environ.get("KGC_DB_URL", "")
IS_PG = DB_URL.startswith(("postgres://", "postgresql://"))

# SQL differences small enough to paper over. Everything else in this module is
# plain SQL that both engines accept, INCLUDING `ON CONFLICT (col) DO UPDATE SET
# x = excluded.x` - so upserts are written that way rather than as SQLite's
# `INSERT OR REPLACE`, which Postgres does not have.
def _sql(q):
    if not IS_PG:
        return q
    return q.replace("?", "%s").replace(" REAL", " DOUBLE PRECISION")


class _Conn:
    """One connection, one transaction, closed on exit - the same contract on both
    engines. `with sqlite3.connect(...)` commits but does NOT close; psycopg's does
    both. Wrapping them makes that difference stop mattering."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, q, params=()):
        return self._raw.execute(_sql(q), params)

    def executemany(self, q, seq):
        # psycopg's Connection has execute() but NOT executemany() - that one lives
        # on the cursor. sqlite3's Connection has both.
        if IS_PG:
            cur = self._raw.cursor()
            cur.executemany(_sql(q), list(seq))
            return cur
        return self._raw.executemany(_sql(q), list(seq))

    def __enter__(self):
        self._raw.__enter__()
        return self

    def __exit__(self, *exc):
        try:
            return self._raw.__exit__(*exc)
        finally:
            if not IS_PG:            # psycopg's __exit__ already closed it
                self._raw.close()


# ponytail: fresh connection per call, no pool. Sub-ms at this request rate; add
# a threading.local cache only if profiling ever says connect() matters.
def _conn():
    if IS_PG:
        try:
            import psycopg
        except ImportError:
            raise SystemExit("KGC_DB_URL points at PostgreSQL but psycopg is not installed: "
                             'pip install "psycopg[binary]"')
        return _Conn(psycopg.connect(DB_URL))
    c = sqlite3.connect(DB_PATH, timeout=10.0)
    c.execute("PRAGMA journal_mode=WAL")     # concurrent readers + one writer, across processes
    c.execute("PRAGMA busy_timeout=10000")   # wait out the other process instead of raising
    c.execute("PRAGMA foreign_keys=ON")      # derived rows follow their player row on delete
    return _Conn(c)


def _columns(c, table):
    """Column names of `table`. PRAGMA is SQLite-only; information_schema is not."""
    if IS_PG:
        return {r[0] for r in c.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=?", (table,))}
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


# --- schema + migrations ----------------------------------------------------
def _baseline(c):
    """v1: what the first SQLite version created. Kept verbatim as the starting point."""
    c.execute("CREATE TABLE IF NOT EXISTS players ("
              "uid TEXT PRIMARY KEY, data TEXT NOT NULL, updated REAL NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    # accessToken -> uid. The client sends it as the `accesstoken` header on
    # every request (Web.Get/Post take it as a parameter), so it is the only
    # per-request identity available.
    c.execute("CREATE TABLE IF NOT EXISTS sessions ("
              "token TEXT PRIMARY KEY, uid TEXT NOT NULL, created REAL NOT NULL)")
    # The client's own account id (register/auth `id`) -> uid. Survives a
    # token being reminted on every login.
    c.execute("CREATE TABLE IF NOT EXISTS accounts ("
              "login_id TEXT PRIMARY KEY, uid TEXT NOT NULL)")


def _m2_indexes(c):
    """Lookups that were full scans, plus the expired sessions nobody ever deleted."""
    c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_uid ON sessions(uid)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounts_uid ON accounts(uid)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_players_updated ON players(updated)")
    c.execute("DELETE FROM sessions WHERE created < ?", (time.time() - SESSION_TTL,))


def _m3_derived(c):
    """Queryable projections of the blob. Rebuilt on every save; never read by game logic."""
    for col, decl in (("name", "TEXT"), ("gold", "INTEGER"), ("cash", "INTEGER"),
                      ("level", "INTEGER"), ("account_type", "INTEGER")):
        cols = _columns(c, "players")
        if col not in cols:
            c.execute(f"ALTER TABLE players ADD COLUMN {col} {decl}")
    c.execute("CREATE TABLE IF NOT EXISTS player_items ("
              "uid TEXT NOT NULL, item_id INTEGER NOT NULL, count INTEGER NOT NULL,"
              "PRIMARY KEY (uid, item_id),"
              "FOREIGN KEY (uid) REFERENCES players(uid) ON DELETE CASCADE)")
    c.execute("CREATE TABLE IF NOT EXISTS player_cards ("
              "uid TEXT NOT NULL, unit_id INTEGER NOT NULL, level INTEGER, soul INTEGER,"
              "PRIMARY KEY (uid, unit_id),"
              "FOREIGN KEY (uid) REFERENCES players(uid) ON DELETE CASCADE)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_player_items_item ON player_items(item_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_player_cards_unit ON player_cards(unit_id)")
    for uid, blob in c.execute("SELECT uid, data FROM players").fetchall():
        try:
            _write_derived(c, uid, json.loads(blob))
        except Exception:
            pass          # a save that will not parse keeps its blob; derived rows stay empty


def _m4_admins(c):
    """Dashboard accounts. Empty table = the old token/loopback rules still apply."""
    c.execute("CREATE TABLE IF NOT EXISTS admins ("
              "username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, created REAL NOT NULL,"
              "last_login REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS admin_sessions ("
              "token TEXT PRIMARY KEY, username TEXT NOT NULL, created REAL NOT NULL,"
              "FOREIGN KEY (username) REFERENCES admins(username) ON DELETE CASCADE)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_admin_sessions_user ON admin_sessions(username)")


# (version, description, fn). Append only - never edit one that has shipped.
MIGRATIONS = [
    (2, "indexes + expired-session sweep", _m2_indexes),
    (3, "derived player_items / player_cards / player columns", _m3_derived),
    (4, "dashboard admin accounts + sessions", _m4_admins),
]
SCHEMA_VERSION = MIGRATIONS[-1][0]


def _schema_version(c):
    row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else 1


def _set_schema_version(c, v):
    c.execute("INSERT INTO meta (key,value) VALUES ('schema_version',?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(v),))


def _backup(tag):
    """Copy the DB aside before a migration. Cheap insurance: the file is <1 MB.

    Postgres has no file to copy and a real backup story of its own (pg_dump, WAL
    archiving), so this steps aside there rather than pretending to protect you."""
    if IS_PG:
        print("[state] Postgres backend: take your own pg_dump before a migration")
        return None
    if not DB_PATH.exists():
        return None
    d = DB_PATH.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"players-{time.strftime('%Y%m%d-%H%M%S')}-{tag}.db"
    # sqlite3's own backup API, so a checkpointed WAL is included and a
    # concurrent writer cannot hand us a torn file the way shutil.copy can.
    src = sqlite3.connect(DB_PATH)
    out = sqlite3.connect(dst)
    with out:
        src.backup(out)
    out.close(); src.close()
    # By mtime, not by name. An older naming scheme put the tag first
    # ("players-manual-20260729-...") so a lexicographic sort ranks it after every
    # timestamp-first name - and this prune would then delete the NEWEST backups
    # while keeping the oldest.
    for f in sorted(d.glob("players-*.db"), key=lambda p: p.stat().st_mtime)[:-BACKUP_KEEP]:
        f.unlink()
    return dst


def backup_if_due(interval, tag="auto", now=None):
    """Back up when `interval` seconds have passed since the last one. Returns the
    path, or None if it was not due.

    The due-check and the timestamp write happen under the cross-process write lock,
    so the :8080 and :8443 processes cannot both decide it is time and produce two
    backups a second apart - the second would evict a genuinely older one, because
    only BACKUP_KEEP files are kept.
    """
    if IS_PG or interval <= 0:
        return None
    now = time.time() if now is None else now
    with write_lock():
        with _conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key='last_backup'").fetchone()
        last = float(row[0]) if row and row[0] else 0.0
        if now - last < interval:
            return None
        with _conn() as c:
            c.execute("INSERT INTO meta (key,value) VALUES ('last_backup',?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now),))
        return _backup(tag)


def init():
    """Create the schema if missing, then apply pending migrations. Idempotent."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    fresh = not DB_PATH.exists()
    with _conn() as c:
        _baseline(c)
        have = SCHEMA_VERSION if fresh else _schema_version(c)
        pending = [m for m in MIGRATIONS if m[0] > have]
    if fresh:
        with _conn() as c:                     # brand new DB: build every table, no backup
            for _v, _d, fn in MIGRATIONS:
                fn(c)
            _set_schema_version(c, SCHEMA_VERSION)
        return SCHEMA_VERSION
    if not pending:
        return have
    _backup(f"v{have}")
    for v, desc, fn in pending:
        with _conn() as c:                     # one transaction per migration
            fn(c)
            _set_schema_version(c, v)
        print(f"[state] migrated schema v{v}: {desc}")
    return SCHEMA_VERSION


# --- derived projections ----------------------------------------------------
_derived_warned = set()

def _derived_warn(exc):
    """Report each distinct derived-write failure once. Loud enough to find, quiet
    enough not to drown the log at request rate."""
    key = f"{type(exc).__name__}: {exc}"
    if key not in _derived_warned:
        _derived_warned.add(key)
        print(f"[state] derived tables not updated ({key}) - "
              f"saves are fine, run playerdb.reindex_all() after fixing", flush=True)


def _write_derived(c, uid, st):
    """Project the blob into the indexed tables. Best effort: a malformed section is
    skipped rather than failing the save, because the blob is what actually matters."""
    c.execute("UPDATE players SET name=?, gold=?, cash=?, level=?, account_type=? WHERE uid=?",
              (st.get("name"), st.get("gold"), st.get("cash"), st.get("level"),
               st.get("accountType"), uid))
    c.execute("DELETE FROM player_items WHERE uid=?", (uid,))
    inv = st.get("inventory") or {}
    ids, counts = inv.get("itemIds") or [], inv.get("counts") or []
    rows, seen = [], set()
    for item_id, n in zip(ids, counts):
        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            continue
        if item_id in seen:      # a duplicated id would violate the PK; last one wins
            continue
        seen.add(item_id)
        rows.append((uid, item_id, int(n or 0)))
    if rows:
        c.executemany("INSERT INTO player_items (uid,item_id,count) VALUES (?,?,?)", rows)
    c.execute("DELETE FROM player_cards WHERE uid=?", (uid,))
    rows, seen = [], set()
    for key, card in (st.get("cards") or {}).items():
        if not isinstance(card, dict):
            continue
        try:
            unit_id = int(card.get("unitId", key))
        except (TypeError, ValueError):
            continue
        if unit_id in seen:
            continue
        seen.add(unit_id)
        rows.append((uid, unit_id, card.get("level"), card.get("soul")))
    if rows:
        c.executemany("INSERT INTO player_cards (uid,unit_id,level,soul) VALUES (?,?,?,?)", rows)


def reindex_all():
    """Rebuild every derived row from the blobs. The derived tables are a cache;
    this is how you prove it, and how you recover if one ever drifts."""
    with _conn() as c:
        n = 0
        for uid, blob in c.execute("SELECT uid, data FROM players").fetchall():
            try:
                _write_derived(c, uid, json.loads(blob))
                n += 1
            except Exception:
                pass
    return n


def load(uid):
    with _conn() as c:
        row = c.execute("SELECT data FROM players WHERE uid=?", (uid,)).fetchone()
    return json.loads(row[0]) if row else None

def save(uid, st):
    blob = json.dumps(st, ensure_ascii=False)
    with _conn() as c:   # context manager = one transaction, commit or rollback
        c.execute("INSERT INTO players (uid, data, updated) VALUES (?,?,?) "
                  "ON CONFLICT(uid) DO UPDATE SET data=excluded.data, updated=excluded.updated",
                  (uid, blob, time.time()))
        try:
            _write_derived(c, uid, st)
        except Exception as e:
            # Never fail a save over the query-only projection - but never lose the
            # reason either. A silent `pass` here hid a Postgres-only bug (psycopg
            # has no Connection.executemany) that left every derived table empty.
            _derived_warn(e)

def delete(uid):
    """Remove the save and everything bound to it - sessions and account bindings
    included, or a deleted player's token keeps resolving and a later login with the
    same account id lands on a uid that no longer exists."""
    with _conn() as c:
        c.execute("DELETE FROM players WHERE uid=?", (uid,))
        c.execute("DELETE FROM sessions WHERE uid=?", (uid,))
        c.execute("DELETE FROM accounts WHERE uid=?", (uid,))
        c.execute("DELETE FROM player_items WHERE uid=?", (uid,))
        c.execute("DELETE FROM player_cards WHERE uid=?", (uid,))
        row = c.execute("SELECT value FROM meta WHERE key='active'").fetchone()
        if row and row[0] == uid:
            c.execute("DELETE FROM meta WHERE key='active'")

def all_players():
    """[(uid, state_dict, updated_epoch)] ordered by uid."""
    with _conn() as c:
        rows = c.execute("SELECT uid, data, updated FROM players ORDER BY uid").fetchall()
    out = []
    for uid, blob, updated in rows:
        try:
            out.append((uid, json.loads(blob), updated))
        except Exception:
            out.append((uid, None, updated))
    return out

def count():
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM players").fetchone()[0]

def account_count():
    """How many login ids are bound to a save. Zero means no account has ever
    logged in, which is what first-login save adoption keys off."""
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]

def active():
    """uid of the player the game client is currently served."""
    with _conn() as c:
        row = c.execute("SELECT value FROM meta WHERE key='active'").fetchone()
        if row and c.execute("SELECT 1 FROM players WHERE uid=?", (row[0],)).fetchone():
            return row[0]
        first = c.execute("SELECT uid FROM players ORDER BY uid LIMIT 1").fetchone()
    return first[0] if first else None

def set_active(uid):
    with _conn() as c:
        c.execute("INSERT INTO meta (key,value) VALUES ('active',?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (uid,))

SESSION_TTL = 7 * 24 * 3600   # matches the expiredAt the login response advertises

def bind_session(token, uid):
    with _conn() as c:
        c.execute("INSERT INTO sessions (token, uid, created) VALUES (?,?,?) "
                  "ON CONFLICT (token) DO UPDATE SET uid=excluded.uid, created=excluded.created",
                  (token, uid, time.time()))
        c.execute("DELETE FROM sessions WHERE created < ?", (time.time() - SESSION_TTL,))

def uid_for_token(token):
    if not token:
        return None
    with _conn() as c:
        row = c.execute("SELECT uid FROM sessions WHERE token=? AND created >= ?",
                        (token, time.time() - SESSION_TTL)).fetchone()
    return row[0] if row else None

def uid_for_login(login_id):
    if not login_id:
        return None
    with _conn() as c:
        row = c.execute("SELECT uid FROM accounts WHERE login_id=?", (login_id,)).fetchone()
    return row[0] if row else None

def bind_login(login_id, uid):
    with _conn() as c:
        c.execute("INSERT INTO accounts (login_id, uid) VALUES (?,?) "
                  "ON CONFLICT (login_id) DO UPDATE SET uid=excluded.uid", (login_id, uid))


def end_session(token):
    """Log out one token. `uid_for_token` already refuses expired rows, but a token
    that is gone can never be replayed, and this is what a logout button needs."""
    if not token:
        return 0
    with _conn() as c:
        return c.execute("DELETE FROM sessions WHERE token=?", (token,)).rowcount


def end_sessions_for(uid):
    """Log a player out everywhere - after a password change, a ban, or a delete."""
    with _conn() as c:
        return c.execute("DELETE FROM sessions WHERE uid=?", (uid,)).rowcount


def purge_sessions(now=None):
    """Drop expired rows. Enforcement is on read; this is what keeps the table small."""
    now = now if now is not None else time.time()
    with _conn() as c:
        return c.execute("DELETE FROM sessions WHERE created < ?", (now - SESSION_TTL,)).rowcount


def vacuum():
    """Reclaim space after a purge or a bulk delete. VACUUM cannot run inside a
    transaction, so this uses a bare connection rather than the `with` form."""
    if IS_PG:
        import psycopg
        with psycopg.connect(DB_URL, autocommit=True) as c:
            c.execute("VACUUM")
        return
    c = sqlite3.connect(DB_PATH, timeout=30.0)
    try:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.execute("VACUUM")
    finally:
        c.close()


def stats():
    """One round-trip health summary for the dashboard / `python3 playerdb.py`."""
    with _conn() as c:
        one = lambda q, *a: c.execute(q, a).fetchone()[0]
        return {
            "schema_version": _schema_version(c),
            "players": one("SELECT COUNT(*) FROM players"),
            "accounts": one("SELECT COUNT(*) FROM accounts"),
            "sessions": one("SELECT COUNT(*) FROM sessions"),
            "sessions_expired": one("SELECT COUNT(*) FROM sessions WHERE created < ?",
                                    time.time() - SESSION_TTL),
            "admins": one("SELECT COUNT(*) FROM admins"),
            "derived_items": one("SELECT COUNT(*) FROM player_items"),
            "derived_cards": one("SELECT COUNT(*) FROM player_cards"),
            "size_bytes": (one("SELECT pg_database_size(current_database())") if IS_PG
                           else (DB_PATH.stat().st_size if DB_PATH.exists() else 0)),
            "backend": "postgresql" if IS_PG else "sqlite",
        }


# --- dashboard admin accounts -----------------------------------------------
# Password hashing is stdlib scrypt: no dependency, memory-hard, and the cost
# parameters live in the stored string so they can be raised later without
# invalidating existing hashes.
_SCRYPT = dict(n=2 ** 14, r=8, p=1)

def hash_password(password, salt=None):
    import hashlib, base64
    salt = salt or os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT["n"], _SCRYPT["r"], _SCRYPT["p"],
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password, stored):
    import hashlib, base64, hmac
    try:
        scheme, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64),
                            n=int(n), r=int(r), p=int(p), dklen=len(base64.b64decode(dk_b64)))
    except Exception:
        return False
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def admin_count():
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM admins").fetchone()[0]


def admin_create(username, password):
    username = (username or "").strip()
    if not username or not password:
        raise ValueError("username and password are required")
    with _conn() as c:
        c.execute("INSERT INTO admins (username, pw_hash, created) VALUES (?,?,?) "
                  "ON CONFLICT (username) DO UPDATE SET pw_hash=excluded.pw_hash, "
                  "created=excluded.created, last_login=NULL",
                  (username, hash_password(password), time.time()))
    return username


def admin_delete(username):
    with _conn() as c:
        c.execute("DELETE FROM admin_sessions WHERE username=?", (username,))
        return c.execute("DELETE FROM admins WHERE username=?", (username,)).rowcount


def admin_list():
    with _conn() as c:
        return [{"username": u, "created": cr, "last_login": ll}
                for u, cr, ll in c.execute(
                    "SELECT username, created, last_login FROM admins ORDER BY username")]


ADMIN_SESSION_TTL = 12 * 3600     # a dashboard session, not a game session

def admin_login(username, password):
    """Return a fresh session token, or None. Constant-ish work either way: an unknown
    user still runs a hash, so response time does not leak which usernames exist."""
    import secrets
    with _conn() as c:
        row = c.execute("SELECT pw_hash FROM admins WHERE username=?", (username or "",)).fetchone()
    stored = row[0] if row else hash_password("\0decoy")
    if not verify_password(password or "", stored) or not row:
        return None
    token = secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute("INSERT INTO admin_sessions (token, username, created) VALUES (?,?,?)",
                  (token, username, time.time()))
        c.execute("DELETE FROM admin_sessions WHERE created < ?",
                  (time.time() - ADMIN_SESSION_TTL,))
        c.execute("UPDATE admins SET last_login=? WHERE username=?", (time.time(), username))
    return token


def admin_for_token(token):
    if not token:
        return None
    with _conn() as c:
        row = c.execute("SELECT username FROM admin_sessions WHERE token=? AND created >= ?",
                        (token, time.time() - ADMIN_SESSION_TTL)).fetchone()
    return row[0] if row else None


def admin_logout(token):
    if not token:
        return 0
    with _conn() as c:
        return c.execute("DELETE FROM admin_sessions WHERE token=?", (token,)).rowcount

@contextlib.contextmanager
def write_lock():
    """Hold across a whole read-modify-write, not just the save.

    A transaction per save stops corruption but NOT lost updates: handlers do
    load_state() -> mutate dict -> save_state(), and a second process finishing
    its save in between writes back a dict that never saw the first change.
    flock is cross-process, unlike threading.Lock.

    ponytail: one global lock, not per-uid. Traffic is a handful of req/s from
    one game client plus a human on the dashboard, so contention is nil. Key the
    lock file by uid if that ever stops being true.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_PATH.parent / ".write.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def migrate_from_json(state_dir):
    """One-shot import of state/players/*.json + the legacy active player.json.

    Guarded by a `meta` flag, NOT by `count()`: the old JSON saves are still on disk
    (state/pre-sqlite-backup/), so a count-only guard re-imported them into any empty
    database - resurrecting deleted players, and breaking every test that starts from
    a fresh temp DB.
    """
    init()
    with _conn() as c:
        done = c.execute("SELECT 1 FROM meta WHERE key='json_migrated'").fetchone()
    if done or count():
        # Already imported (or the DB has rows, so there is nothing to import into).
        # Still retire the files: they are what makes a later empty DB re-import.
        _retire_legacy_json(state_dir)
        if not done:
            with _conn() as c:
                c.execute("INSERT INTO meta (key,value) VALUES ('json_migrated','skipped') "
                          "ON CONFLICT (key) DO UPDATE SET value=excluded.value")
        return 0
    state_dir = Path(state_dir)
    n = 0
    for f in sorted((state_dir / "players").glob("*.json")):
        try:
            st = json.loads(f.read_text())
        except Exception:
            continue
        save(st.get("uid") or f.stem, st)
        n += 1
    legacy = state_dir / "player.json"
    if legacy.exists():
        try:
            st = json.loads(legacy.read_text())
            uid = st.get("uid", "dev-0001")
            if load(uid) is None:
                save(uid, st)
                n += 1
            set_active(uid)
        except Exception:
            pass
    _retire_legacy_json(state_dir)
    with _conn() as c:
        c.execute("INSERT INTO meta (key,value) VALUES ('json_migrated',?) "
                  "ON CONFLICT (key) DO UPDATE SET value=excluded.value", (str(n),))
    return n


def _retire_legacy_json(state_dir):
    """Move the imported JSON out of the way, into state/pre-sqlite-backup/.

    The import used to leave the originals in place next to their own backup copies,
    so ANY later empty database re-imported them - resurrecting players that had been
    deleted on purpose. Moved, never deleted: they are the only copy of a pre-SQLite
    save if something went wrong with the import."""
    state_dir = Path(state_dir)
    dest = state_dir / "pre-sqlite-backup"
    moved = []
    for src in [state_dir / "player.json", *sorted((state_dir / "players").glob("*.json"))]:
        if not src.exists():
            continue
        rel = src.relative_to(state_dir)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():                       # a copy is already there from last time
            target = target.with_suffix(".json.dup")
        shutil.move(str(src), str(target))
        moved.append(str(rel))
    if moved:
        print(f"[state] retired legacy JSON saves -> {dest.name}/: {', '.join(moved)}", flush=True)
    return moved


def _cli(argv):
    """Operator commands against the LIVE store.

    Kept apart from the self-check below, which runs on a throwaway database - an
    operator told to "run playerdb.py" to migrate or back up would otherwise have
    done neither.
    """
    cmd = argv[0]
    if cmd == "--backup":
        tag = argv[1] if len(argv) > 1 else "manual"
        print(_backup(tag))
    elif cmd == "--migrate":
        print(f"schema v{init()} ({DB_PATH})")
    elif cmd == "--stats":
        print(json.dumps(stats(), indent=1))
    elif cmd == "--vacuum":
        init()
        print(f"reclaimed {vacuum():,} bytes")
    elif cmd == "--purge-sessions":
        init()
        print(f"removed {purge_sessions()} expired session(s)")
    else:
        print(__doc__ or "", "\n  --backup [tag]  --migrate  --stats  --vacuum  "
                            "--purge-sessions\n  (no arguments: self-check)")
        return 2
    return 0


if __name__ == "__main__" and len(sys.argv) > 1:
    sys.exit(_cli(sys.argv[1:]))

if __name__ == "__main__":   # self-check: cross-process semantics we depend on
    # Runs against whichever backend is configured. To exercise Postgres:
    #   KGC_DB_URL=postgresql://kgc@127.0.0.1:5432/kgc python3 playerdb.py
    import tempfile
    if not IS_PG:
        DB_PATH = Path(tempfile.mkdtemp()) / "t.db"
    else:
        with _conn() as _c:                    # start from a clean schema every run
            for t in ("player_items", "player_cards", "admin_sessions", "admins",
                      "sessions", "accounts", "players", "meta"):
                _c.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    init()
    assert load("a") is None and active() is None and count() == 0
    save("a", {"uid": "a", "gold": 1})
    save("b", {"uid": "b", "gold": 2})
    assert load("a")["gold"] == 1 and count() == 2
    save("a", {"uid": "a", "gold": 9})          # upsert, not duplicate
    assert load("a")["gold"] == 9 and count() == 2
    assert active() == "a"                       # falls back to first row
    set_active("b"); assert active() == "b"
    delete("b"); assert active() == "a"          # stale active -> first row
    assert [u for u, _, _ in all_players()] == ["a"]
    # a second connection (stands in for the other uvicorn process) sees committed writes
    save("c", {"uid": "c", "gold": 3})
    with _conn() as _c2:
        assert _c2.execute("SELECT data FROM players WHERE uid='c'").fetchone() is not None

    # --- schema version
    with _conn() as _c:
        assert _schema_version(_c) == SCHEMA_VERSION, "fresh DB must be at the head version"
    assert init() == SCHEMA_VERSION, "init() must be idempotent"

    # --- derived projections track the blob
    save("d", {"uid": "d", "name": "Zed", "gold": 5, "cash": 6, "level": 7, "accountType": 4,
               "inventory": {"itemIds": [10, 20, 10], "counts": [1, 2, 99]},
               "cards": {"10260": {"unitId": 10260, "level": 30, "soul": 12}}})
    with _conn() as _c:
        assert _c.execute("SELECT name,gold,cash,level,account_type FROM players WHERE uid='d'"
                          ).fetchone() == ("Zed", 5, 6, 7, 4)
        # a duplicated item id must not blow up the PK - first one wins
        assert _c.execute("SELECT item_id,count FROM player_items WHERE uid='d' ORDER BY item_id"
                          ).fetchall() == [(10, 1), (20, 2)]
        assert _c.execute("SELECT unit_id,level,soul FROM player_cards WHERE uid='d'"
                          ).fetchall() == [(10260, 30, 12)]
    save("d", {"uid": "d", "gold": 50, "inventory": {"itemIds": [10], "counts": [3]}})
    with _conn() as _c:                        # stale rows are replaced, not merged
        assert _c.execute("SELECT COUNT(*) FROM player_items WHERE uid='d'").fetchone()[0] == 1
        assert _c.execute("SELECT COUNT(*) FROM player_cards WHERE uid='d'").fetchone()[0] == 0
    assert reindex_all() >= 1

    # --- delete cascades to sessions, accounts and derived rows
    bind_session("tok-d", "d"); bind_login("acct-d", "d")
    assert uid_for_token("tok-d") == "d" and uid_for_login("acct-d") == "d"
    delete("d")
    assert uid_for_token("tok-d") is None, "a deleted player's token still resolved"
    assert uid_for_login("acct-d") is None, "a deleted player kept its account binding"
    with _conn() as _c:
        assert _c.execute("SELECT COUNT(*) FROM player_items WHERE uid='d'").fetchone()[0] == 0

    # --- session expiry + logout
    bind_session("tok-a", "a")
    assert uid_for_token("tok-a") == "a"
    with _conn() as _c:                        # backdate past the TTL
        _c.execute("UPDATE sessions SET created=? WHERE token='tok-a'",
                   (time.time() - SESSION_TTL - 1,))
    assert uid_for_token("tok-a") is None, "an expired token still resolved"
    assert purge_sessions() >= 1
    bind_session("tok-a2", "a")
    assert end_session("tok-a2") == 1 and uid_for_token("tok-a2") is None
    bind_session("t1", "a"); bind_session("t2", "a")
    assert end_sessions_for("a") == 2

    # --- admin accounts
    assert admin_count() == 0 and admin_login("nobody", "x") is None
    admin_create("root", "hunter2")
    assert admin_login("root", "wrong") is None, "wrong password logged in"
    tok = admin_login("root", "hunter2")
    assert tok and admin_for_token(tok) == "root"
    assert admin_logout(tok) == 1 and admin_for_token(tok) is None
    assert verify_password("hunter2", hash_password("hunter2"))
    assert not verify_password("hunter2", hash_password("hunter3"))
    assert admin_delete("root") == 1 and admin_count() == 0

    s = stats()
    assert s["schema_version"] == SCHEMA_VERSION and s["players"] >= 1, s
    vacuum()
    if IS_PG:
        with _conn() as _c:                    # leave the test database as we found it
            for t in ("player_items", "player_cards", "admin_sessions", "admins",
                      "sessions", "accounts", "players", "meta"):
                _c.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    else:
        os.remove(DB_PATH)
    print(f"playerdb self-check ok ({s['backend']}, schema v{SCHEMA_VERSION}, "
          f"{len(MIGRATIONS)} migrations)")
