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
MAX_LOGIN_ID_LENGTH = 256  # Guest/social identity, never an arbitrary request blob

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


def _m5_lobbies(c):
    """Friendly Battle lobbies - transient rooms keyed by a 6-char code."""
    c.execute("CREATE TABLE IF NOT EXISTS lobbies ("
              "code TEXT PRIMARY KEY, host_uid TEXT NOT NULL, "
              "members TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lobbies_host ON lobbies(host_uid)")


def _m6_player_portal_auth(c):
    """Player-portal credentials and sessions.

    A portal credential identifies an account that already exists in ``accounts``;
    it deliberately does not create a game save.  Google accounts authenticate via
    the existing OAuth flow, while the operator creates credentials only for Guest
    accounts after verifying the player owns that account.
    """
    c.execute("CREATE TABLE IF NOT EXISTS player_login_creds ("
              "login_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, "
              "pw_hash TEXT NOT NULL, created REAL NOT NULL, last_login REAL, "
              "failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until REAL, "
              "must_change_password INTEGER NOT NULL DEFAULT 1)")
    c.execute("CREATE TABLE IF NOT EXISTS player_sessions ("
              "token_hash TEXT PRIMARY KEY, login_id TEXT NOT NULL, created REAL NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS player_portal_ip_locks ("
              "ip TEXT PRIMARY KEY, failed_attempts INTEGER NOT NULL, window_started REAL NOT NULL, "
              "locked_until REAL)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_player_sessions_login "
              "ON player_sessions(login_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_player_creds_username "
              "ON player_login_creds(username)")


def _m7_player_tickets(c):
    """Portal ticket wallet and provider-postback audit trail.

    Provider rewards are an external fact, so every callback gets a durable event
    id before it can alter a wallet.  This makes retries harmless across both
    public uvicorn listeners and preserves an operator audit trail.
    """
    c.execute("CREATE TABLE IF NOT EXISTS ticket_wallets ("
              "login_id TEXT PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0, "
              "last_earned_at REAL, earned_day TEXT, earned_today INTEGER NOT NULL DEFAULT 0)")
    ticket_log_id = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    c.execute("CREATE TABLE IF NOT EXISTS ticket_log ("
              f"id {ticket_log_id}, login_id TEXT NOT NULL, "
              "delta INTEGER NOT NULL, reason TEXT NOT NULL, provider TEXT, "
              "event_id TEXT, ip TEXT, created REAL NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS ticket_provider_sessions ("
              "session_id TEXT PRIMARY KEY, provider TEXT NOT NULL, login_id TEXT NOT NULL, "
              "created REAL NOT NULL, expires REAL NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS ticket_provider_events ("
              "provider TEXT NOT NULL, event_id TEXT NOT NULL, session_id TEXT NOT NULL, "
              "login_id TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, "
              "PRIMARY KEY (provider,event_id))")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ticket_log_login_created "
              "ON ticket_log(login_id,created DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ticket_sessions_expiry "
              "ON ticket_provider_sessions(expires)")


def _m8_player_grant_requests(c):
    """A ticket-backed queue for requests that need an operator's judgement."""
    request_id = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    c.execute("CREATE TABLE IF NOT EXISTS grant_requests ("
              f"id {request_id}, login_id TEXT NOT NULL, uid TEXT NOT NULL, "
              "text TEXT NOT NULL, item_type TEXT, item_id INTEGER, "
              "status TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL, "
              "resolved_at REAL, resolved_by TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_grant_requests_status_created "
              "ON grant_requests(status,created DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_grant_requests_login_created "
              "ON grant_requests(login_id,created DESC)")


def _m9_donations(c):
    """Manual donation notes and their one-time operator ticket credits."""
    donation_id = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    c.execute("CREATE TABLE IF NOT EXISTS donations ("
              f"id {donation_id}, login_id TEXT NOT NULL, note TEXT, amount TEXT, "
              "created REAL NOT NULL, credited_at REAL, credited_by TEXT, credited_tickets INTEGER)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_donations_created ON donations(created DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_donations_uncredited "
              "ON donations(credited_at,created DESC)")


# (version, description, fn). Append only - never edit one that has shipped.
MIGRATIONS = [
    (2, "indexes + expired-session sweep", _m2_indexes),
    (3, "derived player_items / player_cards / player columns", _m3_derived),
    (4, "dashboard admin accounts + sessions", _m4_admins),
    (5, "Friendly Battle lobbies", _m5_lobbies),
    (6, "player portal credentials + sessions", _m6_player_portal_auth),
    (7, "player ticket wallet + provider postbacks", _m7_player_tickets),
    (8, "player ticket-backed grant requests", _m8_player_grant_requests),
    (9, "manual donation notes + one-time ticket credits", _m9_donations),
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


_DECK_SLOTS = 6  # Fixed client UI slots; see server._pad_deck for write-side enforcement.


def _int_or(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load(uid):
    with _conn() as c:
        row = c.execute("SELECT data FROM players WHERE uid=?", (uid,)).fetchone()
    if not row:
        return None
    data = json.loads(row[0])
    
    # Self-heal bad hero data from previous summon bugs (e.g. Unit 42110).
    # This runs before any route sees the state: a malformed card key or a deck
    # entry of the wrong shape used to make every request for that player fail
    # while loading the save, leaving no route able to repair it.
    cards = data.get("cards", {})
    if not isinstance(cards, dict):
        data["cards"] = {}
    else:
        clean_cards = {}
        for cid, card in cards.items():
            unit_id = _int_or(cid, -1)
            if not (10000 <= unit_id < 11000) or not isinstance(card, dict):
                continue
            # The map key is authoritative.  Normalising these two fields keeps
            # cards_list/card_to_dict safe if an old raw-save edit omitted them.
            card["unitId"] = unit_id
            card["level"] = max(1, _int_or(card.get("level"), 1))
            clean_cards[str(unit_id)] = card
        data["cards"] = clean_cards

    decks = data.get("decks", [])
    if not isinstance(decks, list):
        data["decks"] = []
    else:
        clean_decks = []
        for deck_info in decks:
            if not isinstance(deck_info, dict):
                continue
            deck = deck_info.get("deck", [])
            if not isinstance(deck, (list, tuple)):
                deck = []
            repaired = []
            for value in deck[:_DECK_SLOTS]:
                unit_id = _int_or(value, 10000)
                repaired.append(unit_id if unit_id == 0 or 10000 <= unit_id < 11000 else 10000)
            deck_info["deck"] = (repaired + [0] * _DECK_SLOTS)[:_DECK_SLOTS]

            potential = deck_info.get("potential", [])
            if not isinstance(potential, (list, tuple)):
                potential = []
            deck_info["potential"] = [max(0, _int_or(value)) for value in potential[:_DECK_SLOTS]]
            deck_info["potential"] = (deck_info["potential"] + [0] * _DECK_SLOTS)[:_DECK_SLOTS]
            deck_info["firstComerIndex"] = max(0, _int_or(deck_info.get("firstComerIndex")))
            clean_decks.append(deck_info)
        data["decks"] = clean_decks
                
    return data

def save(uid, st):
    # The row key is authoritative: a save loaded under one uid must never write
    # back under its stale inner uid (the 2787e1 migration copy carried inner
    # uid=0c10a2, so every gameplay write silently landed on the other row).
    st["uid"] = uid
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

def next_account_id():
    """A fresh, unique accountId (max of existing + 1). The client's
    targetId/profile lookups key off it, so it must never collide."""
    best = 0
    for _uid, s, _ in all_players():
        if s is not None:
            try:
                v = int(s.get("accountId", 0) or 0)
            except (ValueError, TypeError):
                v = 0
            if v > best:
                best = v
    return best + 1

def backfill_account_ids():
    """Make accountId unique across all saves. Templates seed accountId=1, so
    every pre-2026-08 save collides; this keeps the first row's id stable and
    reassigns the rest. Idempotent: only touches missing or duplicated ids."""
    taken = set()
    changed = 0
    for uid, s, _ in all_players():
        if s is None:
            continue
        try:
            v = int(s.get("accountId", 0) or 0)
        except (ValueError, TypeError):
            # A malformed raw-save value is equivalent to a missing id.  Leaving
            # it alone makes every leaderboard's int(accountId) conversion fail.
            v = 0
        if v > 0 and v not in taken:
            taken.add(v)
            continue
        nv = next_account_id()
        while nv in taken:
            nv += 1
        s["accountId"] = nv
        save(uid, s)
        taken.add(nv)
        changed += 1
    return changed

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
    # Headers are strings, but /auth/login also accepts a body token.  Never
    # hand an arbitrary decoded JSON value to a DB driver: dict/list values are
    # unbindable in SQLite and used to turn an otherwise recoverable bad login
    # into a handler exception.
    if not isinstance(token, str) or not token:
        return None
    with _conn() as c:
        row = c.execute("SELECT uid FROM sessions WHERE token=? AND created >= ?",
                        (token, time.time() - SESSION_TTL)).fetchone()
    return row[0] if row else None

def valid_login_id(login_id):
    """Whether an external account identity is safe to persist as an index key."""
    return isinstance(login_id, str) and 0 < len(login_id) <= MAX_LOGIN_ID_LENGTH


def uid_for_login(login_id):
    if not valid_login_id(login_id):
        return None
    with _conn() as c:
        row = c.execute("SELECT uid FROM accounts WHERE login_id=?", (login_id,)).fetchone()
    return row[0] if row else None

def bind_login(login_id, uid):
    if not valid_login_id(login_id):
        raise ValueError("invalid login id")
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


# --- Friendly Battle lobbies ------------------------------------------------

def lobby_create(code, host_uid):
    """Create a new lobby with the given code and host.  Members stored as JSON list."""
    import json as _json
    with _conn() as c:
        c.execute("INSERT INTO lobbies (code, host_uid, members, created_at) "
                  "VALUES (?, ?, ?, ?)",
                  (code, host_uid, _json.dumps([host_uid]), time.time()))

def lobby_get(code):
    """Return the lobby row as a dict, or None."""
    import json as _json
    with _conn() as c:
        row = c.execute("SELECT code, host_uid, members, created_at "
                        "FROM lobbies WHERE code=?", (code,)).fetchone()
    if not row:
        return None
    return {"code": row[0], "host_uid": row[1],
            "members": _json.loads(row[2]), "created_at": row[3]}

def lobby_get_by_uid(uid):
    """Return the lobby a player belongs to, or None."""
    import json as _json
    with _conn() as c:
        row = c.execute("SELECT code, host_uid, members, created_at "
                        "FROM lobbies WHERE host_uid=?", (uid,)).fetchone()
        if not row:
            # Check members JSON array
            for r in c.execute("SELECT code, host_uid, members, created_at "
                               "FROM lobbies"):
                if uid in _json.loads(r[2]):
                    row = r
                    break
    if not row:
        return None
    return {"code": row[0], "host_uid": row[1],
            "members": _json.loads(row[2]), "created_at": row[3]}

def lobby_join(code, uid):
    """Add a player to the lobby.  Returns False if lobby is full (4 players)."""
    import json as _json
    with _conn() as c:
        row = c.execute("SELECT members FROM lobbies WHERE code=?", (code,)).fetchone()
        if not row:
            return False
        members = _json.loads(row[0])
        if uid in members:
            return True  # already in
        if len(members) >= 4:
            return False
        members.append(uid)
        c.execute("UPDATE lobbies SET members=? WHERE code=?",
                  (_json.dumps(members), code))
    return True

def lobby_leave(code, uid):
    """Remove a player from the lobby.  If the host leaves, the lobby is deleted."""
    import json as _json
    with _conn() as c:
        row = c.execute("SELECT host_uid, members FROM lobbies WHERE code=?",
                        (code,)).fetchone()
        if not row:
            return
        host_uid, members_json = row
        members = _json.loads(members_json)
        if uid not in members:
            return
        if uid == host_uid:
            c.execute("DELETE FROM lobbies WHERE code=?", (code,))
        else:
            members.remove(uid)
            c.execute("UPDATE lobbies SET members=? WHERE code=?",
                      (_json.dumps(members), code))

def lobby_leave_by_uid(uid):
    """Remove a player from whatever lobby they are in."""
    lobby = lobby_get_by_uid(uid)
    if lobby:
        lobby_leave(lobby["code"], uid)

def lobby_members(code):
    """Return [{"uid": ...}, ...] for every member in the lobby."""
    lobby = lobby_get(code)
    if not lobby:
        return []
    return [{"uid": u} for u in lobby["members"]]

def lobby_cleanup(max_age=3600):
    """Delete lobbies older than max_age seconds (default 1 hour)."""
    with _conn() as c:
        c.execute("DELETE FROM lobbies WHERE created_at < ?",
                  (time.time() - max_age,))


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

def admin_change_password(username, old_password, new_password, keep_token=None):
    """Verify old_password, then replace the hash. Returns True on success, False
    when the old password is wrong. Revokes every session for the account except
    keep_token (the caller's own, so the change does not log them out)."""
    if not username or not new_password:
        return False
    with _conn() as c:
        row = c.execute("SELECT pw_hash FROM admins WHERE username=? COLLATE NOCASE",
                        (username,)).fetchone()
    if not row or not verify_password(old_password or "", row[0]):
        return False
    with _conn() as c:
        c.execute("UPDATE admins SET pw_hash=? WHERE username=? COLLATE NOCASE",
                  (hash_password(new_password), username))
        if keep_token:
            c.execute("DELETE FROM admin_sessions WHERE username=? AND token<>?",
                      (username, keep_token))
        else:
            c.execute("DELETE FROM admin_sessions WHERE username=?", (username,))
    return True


def admin_login(username, password):
    """Return a fresh session token, or None. Constant-ish work either way: an unknown
    user still runs a hash, so response time does not leak which usernames exist."""
    import secrets
    with _conn() as c:
        row = c.execute("SELECT username, pw_hash FROM admins WHERE username=? COLLATE NOCASE",
                        (username or "",)).fetchone()
    stored = row[1] if row else hash_password("\0decoy")
    if not verify_password(password or "", stored) or not row:
        return None
    username = row[0]
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


# --- player portal accounts -------------------------------------------------
# The game already owns the durable identity (accounts.login_id -> uid).  The
# portal adds a browser session around that identity; it must never create a
# separate ``player_<name>`` account that can drift away from the game save.
PLAYER_PORTAL_SESSION_TTL = 7 * 24 * 3600
PLAYER_PORTAL_LOCKOUT_SECONDS = 10 * 60
PLAYER_PORTAL_MAX_FAILURES = 5


def _portal_token_hash(token):
    import hashlib
    return hashlib.sha256((token or "").encode()).hexdigest()


def login_ids_for_uid(uid):
    """All game login ids bound to ``uid`` (for the operator's Guest-access UI)."""
    with _conn() as c:
        return [r[0] for r in c.execute(
            "SELECT login_id FROM accounts WHERE uid=? ORDER BY login_id", (uid,))]


def portal_access_for_uid(uid):
    """Game identities plus any operator-issued Guest portal credential metadata."""
    with _conn() as c:
        rows = c.execute(
            "SELECT a.login_id,c.username,c.created,c.last_login,c.must_change_password "
            "FROM accounts a LEFT JOIN player_login_creds c ON c.login_id=a.login_id "
            "WHERE a.uid=? ORDER BY a.login_id", (uid,)).fetchall()
    return [{"login_id": login_id, "username": username, "created": created,
             "last_login": last_login, "must_change_password": bool(must_change)}
            for login_id, username, created, last_login, must_change in rows]


def portal_guest_access(login_id, username, password, now=None):
    """Create or replace an operator-issued Guest portal credential.

    The account has to have entered the game first.  Otherwise an operator typo
    would silently reserve a login id and the portal could point at no save.
    """
    login_id = str(login_id or "").strip()
    username = str(username or "").strip().lower()
    password = password or ""
    now = time.time() if now is None else now
    if not login_id.startswith("Guest_"):
        raise ValueError("portal passwords are only for Guest accounts")
    if not (3 <= len(username) <= 20) or not username.replace("_", "").isalnum():
        raise ValueError("username must be 3-20 letters, numbers, or underscores")
    if len(password) < 8:
        raise ValueError("temporary password must be at least 8 characters")
    with _conn() as c:
        if not c.execute("SELECT 1 FROM accounts WHERE login_id=?", (login_id,)).fetchone():
            raise ValueError("Guest account has not entered the game yet")
        existing = c.execute(
            "SELECT login_id FROM player_login_creds WHERE username=? COLLATE NOCASE",
            (username,)).fetchone()
        if existing and existing[0] != login_id:
            raise ValueError("portal username is already in use")
        c.execute("INSERT INTO player_login_creds "
                  "(login_id,username,pw_hash,created,last_login,failed_attempts,locked_until,must_change_password) "
                  "VALUES (?,?,?,?,NULL,0,NULL,1) "
                  "ON CONFLICT(login_id) DO UPDATE SET username=excluded.username, "
                  "pw_hash=excluded.pw_hash, failed_attempts=0, locked_until=NULL, "
                  "must_change_password=1",
                  (login_id, username, hash_password(password), now))
        c.execute("DELETE FROM player_sessions WHERE login_id=?", (login_id,))
    return {"login_id": login_id, "username": username, "must_change_password": True}


def _portal_create_session(c, login_id, now):
    import secrets
    token = secrets.token_urlsafe(32)
    c.execute("INSERT INTO player_sessions(token_hash,login_id,created) VALUES (?,?,?)",
              (_portal_token_hash(token), login_id, now))
    c.execute("DELETE FROM player_sessions WHERE created < ?",
              (now - PLAYER_PORTAL_SESSION_TTL,))
    return token


def _portal_ip_is_locked(c, ip, now):
    if not ip:
        return False
    row = c.execute("SELECT locked_until FROM player_portal_ip_locks WHERE ip=?", (ip,)).fetchone()
    return bool(row and row[0] and row[0] > now)


def _portal_record_ip_failure(c, ip, now):
    if not ip:
        return
    row = c.execute("SELECT failed_attempts,window_started FROM player_portal_ip_locks WHERE ip=?",
                    (ip,)).fetchone()
    if not row or now - row[1] >= PLAYER_PORTAL_LOCKOUT_SECONDS:
        failures, started = 1, now
    else:
        failures, started = int(row[0]) + 1, row[1]
    locked_until = now + PLAYER_PORTAL_LOCKOUT_SECONDS \
        if failures >= PLAYER_PORTAL_MAX_FAILURES else None
    c.execute("INSERT INTO player_portal_ip_locks(ip,failed_attempts,window_started,locked_until) "
              "VALUES (?,?,?,?) ON CONFLICT(ip) DO UPDATE SET failed_attempts=excluded.failed_attempts, "
              "window_started=excluded.window_started,locked_until=excluded.locked_until",
              (ip, failures, started, locked_until))


def portal_password_login(username, password, ip=None, now=None):
    """Authenticate an operator-issued Guest credential.

    Returns ``(token, login_id, must_change_password, locked)``.  Unknown users
    still run a scrypt verification so timing does not reveal which portal names
    exist.  The counter lives in SQLite because :8080/:8443 and Gunicorn workers
    do not share process memory.
    """
    now = time.time() if now is None else now
    username = str(username or "").strip()
    with _conn() as c:
        row = c.execute("SELECT login_id,pw_hash,failed_attempts,locked_until,must_change_password "
                        "FROM player_login_creds WHERE username=? COLLATE NOCASE",
                        (username,)).fetchone()
        stored = row[1] if row else _PORTAL_DECOY_HASH
        if _portal_ip_is_locked(c, ip, now) or (row and row[3] and row[3] > now):
            # Keep the same scrypt work even while locked, otherwise lockout leaks
            # the user name and becomes a cheap username oracle.
            verify_password(password or "", stored)
            return None, None, False, True
        valid = verify_password(password or "", stored)
        if not row or not valid:
            _portal_record_ip_failure(c, ip, now)
            if row:
                failures = int(row[2] or 0) + 1
                locked_until = now + PLAYER_PORTAL_LOCKOUT_SECONDS \
                    if failures >= PLAYER_PORTAL_MAX_FAILURES else None
                c.execute("UPDATE player_login_creds SET failed_attempts=?,locked_until=? "
                          "WHERE login_id=?", (failures, locked_until, row[0]))
            return None, None, False, False
        token = _portal_create_session(c, row[0], now)
        if ip:
            c.execute("DELETE FROM player_portal_ip_locks WHERE ip=?", (ip,))
        c.execute("UPDATE player_login_creds SET failed_attempts=0,locked_until=NULL,last_login=? "
                  "WHERE login_id=?", (now, row[0]))
        return token, row[0], bool(row[4]), False


def portal_google_login(login_id, now=None):
    """Issue a browser session only for an existing Google-backed game account."""
    login_id = str(login_id or "")
    if not login_id.startswith("google_"):
        return None
    now = time.time() if now is None else now
    with _conn() as c:
        if not c.execute("SELECT 1 FROM accounts WHERE login_id=?", (login_id,)).fetchone():
            return None
        return _portal_create_session(c, login_id, now)


def portal_for_token(token, now=None):
    if not token:
        return None
    now = time.time() if now is None else now
    with _conn() as c:
        row = c.execute("SELECT login_id FROM player_sessions "
                        "WHERE token_hash=? AND created >= ?",
                        (_portal_token_hash(token), now - PLAYER_PORTAL_SESSION_TTL)).fetchone()
    return row[0] if row else None


def portal_logout(token):
    if not token:
        return 0
    with _conn() as c:
        return c.execute("DELETE FROM player_sessions WHERE token_hash=?",
                         (_portal_token_hash(token),)).rowcount


def portal_change_password(login_id, old_password, new_password):
    """Rotate one Guest credential and revoke its other browser sessions."""
    login_id = str(login_id or "")
    if len(new_password or "") < 8:
        raise ValueError("new password must be at least 8 characters")
    with _conn() as c:
        row = c.execute("SELECT pw_hash FROM player_login_creds WHERE login_id=?",
                        (login_id,)).fetchone()
        if not row or not verify_password(old_password or "", row[0]):
            return False
        c.execute("UPDATE player_login_creds SET pw_hash=?,must_change_password=0, "
                  "failed_attempts=0,locked_until=NULL WHERE login_id=?",
                  (hash_password(new_password), login_id))
        c.execute("DELETE FROM player_sessions WHERE login_id=?", (login_id,))
    return True


# Calculated once.  Creating a fresh scrypt hash for every unknown username would
# let an attacker turn failed logins into needless random-memory work.
_PORTAL_DECOY_HASH = hash_password("\0portal-decoy")


# --- player tickets ---------------------------------------------------------
# Ticket amounts remain server-owned virtual currency. A browser prepares a
# rewarded video session; the completion adapter alone reaches
# credit_ticket_from_provider().
TICKET_BALANCE_CAP = 10
TICKET_DAILY_CAP = 20
TICKET_COOLDOWN_SECONDS = 5 * 60
TICKET_PROVIDER_SESSION_TTL = 30 * 24 * 3600


class TicketUnavailable(ValueError):
    def __init__(self, code, cooldown_left=0):
        super().__init__(code)
        self.code = code
        self.cooldown_left = max(0, int(cooldown_left))


def _ticket_day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _ticket_wallet(c, login_id, now):
    """Return one normalized wallet row, resetting only its UTC daily counter."""
    c.execute("INSERT INTO ticket_wallets(login_id,balance,last_earned_at,earned_day,earned_today) "
              "VALUES (?,0,NULL,?,0) ON CONFLICT(login_id) DO NOTHING",
              (login_id, _ticket_day(now)))
    row = c.execute("SELECT balance,last_earned_at,earned_day,earned_today "
                    "FROM ticket_wallets WHERE login_id=?", (login_id,)).fetchone()
    balance, last_earned_at, earned_day, earned_today = row
    today = _ticket_day(now)
    if earned_day != today:
        earned_day, earned_today = today, 0
        c.execute("UPDATE ticket_wallets SET earned_day=?,earned_today=0 WHERE login_id=?",
                  (today, login_id))
    return int(balance), last_earned_at, earned_day, int(earned_today)


def _ticket_snapshot(balance, last_earned_at, earned_today, now):
    cooldown_left = 0 if not last_earned_at else max(
        0, int(TICKET_COOLDOWN_SECONDS - (now - last_earned_at)))
    return {
        "balance": balance,
        "cap": TICKET_BALANCE_CAP,
        "dailyCap": TICKET_DAILY_CAP,
        "dailyEarned": earned_today,
        "cooldownLeftSec": cooldown_left,
    }


def ticket_status(login_id, now=None):
    """Wallet state for a signed-in portal player; daily reset is UTC."""
    now = time.time() if now is None else now
    with write_lock():
        with _conn() as c:
            balance, last_earned_at, _day, earned_today = _ticket_wallet(c, login_id, now)
            return _ticket_snapshot(balance, last_earned_at, earned_today, now)


def ticket_start_provider_session(login_id, provider="gam", now=None):
    """Issue an opaque provider user id after enforcing local earning limits.

    The value is random and only maps to a login ID in SQLite; exposing it to the
    video adapter cannot reveal or let a caller choose another game account.
    """
    import secrets
    now = time.time() if now is None else now
    with write_lock():
        with _conn() as c:
            balance, last_earned_at, _day, earned_today = _ticket_wallet(c, login_id, now)
            snapshot = _ticket_snapshot(balance, last_earned_at, earned_today, now)
            if balance >= TICKET_BALANCE_CAP:
                raise TicketUnavailable("wallet_full")
            if earned_today >= TICKET_DAILY_CAP:
                raise TicketUnavailable("daily_limit")
            if snapshot["cooldownLeftSec"]:
                raise TicketUnavailable("cooldown", snapshot["cooldownLeftSec"])
            c.execute("DELETE FROM ticket_provider_sessions WHERE expires < ?", (now,))
            session_id = secrets.token_urlsafe(24)
            c.execute("INSERT INTO ticket_provider_sessions "
                      "(session_id,provider,login_id,created,expires) VALUES (?,?,?,?,?)",
                      (session_id, provider, login_id, now, now + TICKET_PROVIDER_SESSION_TTL))
    return session_id


def ticket_credit_from_provider(provider, event_id, session_id, ip=None, now=None):
    """Idempotently credit exactly one ticket from a verified provider event.

    Caller authentication belongs to the provider adapter.  This function owns
    all persistence/economic invariants and intentionally never accepts an amount
    from the advertising network.
    """
    provider = str(provider or "")
    event_id = str(event_id or "").strip()
    session_id = str(session_id or "").strip()
    if not provider or not session_id or not (1 <= len(event_id) <= 200):
        raise ValueError("invalid provider event")
    now = time.time() if now is None else now
    with write_lock():
        with _conn() as c:
            old = c.execute("SELECT login_id,status FROM ticket_provider_events "
                            "WHERE provider=? AND event_id=?", (provider, event_id)).fetchone()
            if old:
                balance, last_earned_at, _day, earned_today = _ticket_wallet(c, old[0], now)
                return {"credited": False, "duplicate": True, "status": old[1],
                        **_ticket_snapshot(balance, last_earned_at, earned_today, now)}
            session = c.execute("SELECT login_id FROM ticket_provider_sessions "
                                "WHERE session_id=? AND provider=? AND expires >= ?",
                                (session_id, provider, now)).fetchone()
            if not session:
                raise ValueError("unknown or expired provider session")
            login_id = session[0]
            balance, last_earned_at, _day, earned_today = _ticket_wallet(c, login_id, now)
            snapshot = _ticket_snapshot(balance, last_earned_at, earned_today, now)
            status = None
            if balance >= TICKET_BALANCE_CAP:
                status = "wallet_full"
            elif earned_today >= TICKET_DAILY_CAP:
                status = "daily_limit"
            elif snapshot["cooldownLeftSec"]:
                status = "cooldown"
            if status:
                c.execute("INSERT INTO ticket_provider_events "
                          "(provider,event_id,session_id,login_id,status,created) VALUES (?,?,?,?,?,?)",
                          (provider, event_id, session_id, login_id, status, now))
                return {"credited": False, "duplicate": False, "status": status, **snapshot}
            balance += 1
            earned_today += 1
            c.execute("UPDATE ticket_wallets SET balance=?,last_earned_at=?,earned_day=?,earned_today=? "
                      "WHERE login_id=?", (balance, now, _ticket_day(now), earned_today, login_id))
            c.execute("INSERT INTO ticket_provider_events "
                      "(provider,event_id,session_id,login_id,status,created) VALUES (?,?,?,?,?,?)",
                      (provider, event_id, session_id, login_id, "credited", now))
            c.execute("INSERT INTO ticket_log(login_id,delta,reason,provider,event_id,ip,created) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (login_id, 1, "provider_reward", provider, event_id, ip, now))
            return {"credited": True, "duplicate": False, "status": "credited",
                    **_ticket_snapshot(balance, now, earned_today, now)}


def ticket_history(login_id, limit=50):
    limit = max(1, min(int(limit or 50), 100))
    with _conn() as c:
        rows = c.execute("SELECT delta,reason,provider,event_id,created FROM ticket_log "
                         "WHERE login_id=? ORDER BY id DESC LIMIT ?", (login_id, limit)).fetchall()
    return [{"delta": delta, "reason": reason, "provider": provider,
             "eventId": event_id, "created": created} for delta, reason, provider, event_id, created in rows]


# --- donations and operator ticket top-ups ---------------------------------
def _donation_row(row):
    return {"id": int(row[0]), "loginId": row[1], "note": row[2], "amount": row[3],
            "created": row[4], "creditedAt": row[5], "creditedBy": row[6],
            "creditedTickets": row[7]}


def donation_submit(login_id, note, amount=None, now=None):
    """Record a transfer note. It never changes a ticket balance."""
    login_id = str(login_id or "").strip()
    note = str(note or "").strip()
    amount = str(amount or "").strip() or None
    if not login_id:
        raise ValueError("invalid portal account")
    if not (1 <= len(note) <= 1_000):
        raise ValueError("donation note must be between 1 and 1000 characters")
    if amount and len(amount) > 100:
        raise ValueError("donation amount is too long")
    now = time.time() if now is None else now
    with write_lock():
        with _conn() as c:
            account = c.execute("SELECT uid FROM accounts WHERE login_id=?", (login_id,)).fetchone()
            if not account or not c.execute("SELECT 1 FROM players WHERE uid=?", (account[0],)).fetchone():
                raise ValueError("game account is no longer available")
            if IS_PG:
                donation_id = c.execute(
                    "INSERT INTO donations(login_id,note,amount,created) VALUES (?,?,?,?) RETURNING id",
                    (login_id, note, amount, now)).fetchone()[0]
            else:
                donation_id = c.execute(
                    "INSERT INTO donations(login_id,note,amount,created) VALUES (?,?,?,?)",
                    (login_id, note, amount, now)).lastrowid
            return {"donationId": int(donation_id)}


def donations(limit=100):
    """Newest manual donation notes for the operator dashboard."""
    limit = max(1, min(int(limit or 100), 200))
    with _conn() as c:
        rows = c.execute("SELECT id,login_id,note,amount,created,credited_at,credited_by,credited_tickets "
                         "FROM donations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_donation_row(row) for row in rows]


def admin_credit_tickets(login_id, count, reason, credited_by, donation_id=None, now=None):
    """Operator-only ticket credit, optionally settling one donation exactly once."""
    login_id = str(login_id or "").strip()
    reason = str(reason or "").strip()
    credited_by = str(credited_by or "local-operator").strip()[:80] or "local-operator"
    try:
        count = int(count)
    except (TypeError, ValueError):
        raise ValueError("ticket count must be an integer")
    if not login_id or not (1 <= count <= 10_000):
        raise ValueError("ticket count must be between 1 and 10000")
    if not (1 <= len(reason) <= 500):
        raise ValueError("top-up reason must be between 1 and 500 characters")
    if donation_id is not None:
        try:
            donation_id = int(donation_id)
        except (TypeError, ValueError):
            raise ValueError("invalid donation id")
    now = time.time() if now is None else now
    with write_lock():
        with _conn() as c:
            if donation_id is not None:
                donation = c.execute("SELECT login_id,credited_at FROM donations WHERE id=?", (donation_id,)).fetchone()
                if not donation:
                    raise ValueError("donation not found")
                if donation[1] is not None:
                    raise ValueError("donation is already credited")
                if donation[0] != login_id:
                    raise ValueError("donation does not belong to this account")
            if not c.execute("SELECT 1 FROM accounts WHERE login_id=?", (login_id,)).fetchone():
                raise ValueError("game account is no longer available")
            balance, last_earned_at, _day, earned_today = _ticket_wallet(c, login_id, now)
            balance += count
            c.execute("UPDATE ticket_wallets SET balance=? WHERE login_id=?", (balance, login_id))
            event_id = f"donation:{donation_id}" if donation_id is not None else reason
            c.execute("INSERT INTO ticket_log(login_id,delta,reason,provider,event_id,ip,created) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (login_id, count, "admin_topup", "admin", event_id, None, now))
            if donation_id is not None:
                c.execute("UPDATE donations SET credited_at=?,credited_by=?,credited_tickets=? WHERE id=? "
                          "AND credited_at IS NULL", (now, credited_by, count, donation_id))
            return {"loginId": login_id, "count": count,
                    **_ticket_snapshot(balance, last_earned_at, earned_today, now)}


def _append_portal_mail(st, title, text, reward_type="", reward_id=0, reward_amount=0):
    """Append one mail in a save already owned by the current DB transaction."""
    posts = st.setdefault("posts", [])
    post_id = max((int(p.get("id", 0) or 0) for p in posts if isinstance(p, dict)), default=0) + 1
    # `routes.inbox._process_posts()` adds @raw: only on the game wire. Persisting
    # ordinary text avoids exposing the implementation marker to the player.
    from common import now_iso
    posts.append({
        "id": post_id, "type": "Normal", "title": str(title), "text": str(text),
        "rewardType": str(reward_type), "rewardId": int(reward_id),
        "rewardAmount": int(reward_amount), "untilAt": now_iso(30),
    })
    return post_id


def _request_row(row):
    return {
        "id": int(row[0]), "loginId": row[1], "uid": row[2], "text": row[3],
        "itemType": row[4], "itemId": row[5], "status": row[6],
        "created": row[7], "resolvedAt": row[8], "resolvedBy": row[9],
    }


def _request_text(value):
    text = str(value or "").strip()
    if not (1 <= len(text) <= 500):
        raise ValueError("request text must be between 1 and 500 characters")
    return text


def _request_item(item_type, item_id):
    item_type = str(item_type or "").strip()
    if len(item_type) > 80:
        raise ValueError("requested item type is too long")
    if item_id in (None, ""):
        return item_type or None, None
    try:
        return item_type or None, int(item_id)
    except (TypeError, ValueError):
        raise ValueError("requested item id must be an integer")


def ticket_submit_grant_request(login_id, text, item_type=None, item_id=None, now=None):
    """Spend exactly one ticket and create a pending operator request atomically."""
    login_id = str(login_id or "")
    text = _request_text(text)
    item_type, item_id = _request_item(item_type, item_id)
    if not login_id:
        raise ValueError("invalid portal account")
    now = time.time() if now is None else now
    with write_lock():
        with _conn() as c:
            account = c.execute("SELECT uid FROM accounts WHERE login_id=?", (login_id,)).fetchone()
            if not account:
                raise ValueError("game account is no longer available")
            uid = account[0]
            if not c.execute("SELECT 1 FROM players WHERE uid=?", (uid,)).fetchone():
                raise ValueError("enter the game before submitting a request")
            balance, last_earned_at, _day, earned_today = _ticket_wallet(c, login_id, now)
            if balance < 1:
                raise TicketUnavailable("insufficient_tickets")
            if IS_PG:
                request_id = c.execute(
                    "INSERT INTO grant_requests(login_id,uid,text,item_type,item_id,status,created) "
                    "VALUES (?,?,?,?,?,'pending',?) RETURNING id",
                    (login_id, uid, text, item_type, item_id, now)).fetchone()[0]
            else:
                request_id = c.execute(
                    "INSERT INTO grant_requests(login_id,uid,text,item_type,item_id,status,created) "
                    "VALUES (?,?,?,?,?,'pending',?)",
                    (login_id, uid, text, item_type, item_id, now)).lastrowid
            c.execute("UPDATE ticket_wallets SET balance=? WHERE login_id=?", (balance - 1, login_id))
            c.execute("INSERT INTO ticket_log(login_id,delta,reason,provider,event_id,ip,created) "
                      "VALUES (?,?,?,?,?,?,?)", (login_id, -1, "request", None, None, None, now))
            return {"requestId": int(request_id),
                    **_ticket_snapshot(balance - 1, last_earned_at, earned_today, now)}


def grant_requests(status=None, login_id=None, limit=100):
    """Read request rows, scoped to one player when called by the public portal."""
    if status not in (None, "pending", "approved", "denied"):
        raise ValueError("invalid request status")
    limit = max(1, min(int(limit or 100), 200))
    clauses, params = [], []
    if status:
        clauses.append("status=?")
        params.append(status)
    if login_id:
        clauses.append("login_id=?")
        params.append(str(login_id))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with _conn() as c:
        rows = c.execute("SELECT id,login_id,uid,text,item_type,item_id,status,created,resolved_at,resolved_by "
                         "FROM grant_requests" + where + " ORDER BY id DESC LIMIT ?",
                         tuple(params + [limit])).fetchall()
    return [_request_row(row) for row in rows]


def resolve_grant_request(request_id, action, resolved_by, reward_type=None, reward_id=None,
                          reward_amount=None, reward_name=None, deny_reason=None, now=None):
    """Resolve one pending request; approval mails a reward, denial refunds its ticket.

    State, mailbox, ticket log, and request status commit together. A second admin
    cannot resolve the same request because the pending status is checked inside the
    cross-process lock and transaction.
    """
    try:
        request_id = int(request_id)
    except (TypeError, ValueError):
        raise ValueError("invalid request id")
    if action not in ("approve", "deny"):
        raise ValueError("invalid request action")
    resolved_by = str(resolved_by or "local-operator").strip()[:80] or "local-operator"
    now = time.time() if now is None else now
    if action == "approve":
        reward_type, reward_name = str(reward_type or "").strip(), str(reward_name or "").strip()
        try:
            reward_id, reward_amount = int(reward_id), int(reward_amount)
        except (TypeError, ValueError):
            raise ValueError("reward id and amount must be integers")
        if not reward_type or not reward_name or reward_amount < 1:
            raise ValueError("a reward type, name, and positive amount are required")
    else:
        deny_reason = str(deny_reason or "").strip()[:500]

    with write_lock():
        with _conn() as c:
            row = c.execute("SELECT id,login_id,uid,text,item_type,item_id,status,created,resolved_at,resolved_by "
                            "FROM grant_requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise ValueError("request not found")
            request = _request_row(row)
            if request["status"] != "pending":
                raise ValueError("request is already resolved")
            saved = c.execute("SELECT data FROM players WHERE uid=?", (request["uid"],)).fetchone()
            if not saved:
                raise ValueError("game save is no longer available")
            st = json.loads(saved[0])
            if action == "approve":
                post_id = _append_portal_mail(
                    st, "Yêu cầu Player Portal đã được duyệt",
                    f"Yêu cầu của bạn đã được duyệt: {request['text']}",
                    reward_type, reward_id, reward_amount)
                result = {"refunded": False, "postId": post_id}
            else:
                balance, last_earned_at, _day, earned_today = _ticket_wallet(c, request["loginId"], now)
                balance += 1
                c.execute("UPDATE ticket_wallets SET balance=? WHERE login_id=?",
                          (balance, request["loginId"]))
                c.execute("INSERT INTO ticket_log(login_id,delta,reason,provider,event_id,ip,created) "
                          "VALUES (?,?,?,?,?,?,?)",
                          (request["loginId"], 1, "refund", None, str(request_id), None, now))
                detail = "Yêu cầu của bạn đã bị từ chối. 1 ticket đã được hoàn lại."
                if deny_reason:
                    detail += f" Lý do: {deny_reason}"
                post_id = _append_portal_mail(st, "Yêu cầu Player Portal", detail)
                result = {"refunded": True, "postId": post_id,
                          **_ticket_snapshot(balance, last_earned_at, earned_today, now)}
            st["uid"] = request["uid"]
            c.execute("UPDATE players SET data=?,updated=? WHERE uid=?",
                      (json.dumps(st, ensure_ascii=False), now, request["uid"]))
            try:
                _write_derived(c, request["uid"], st)
            except Exception as e:
                _derived_warn(e)
            c.execute("UPDATE grant_requests SET status=?,resolved_at=?,resolved_by=? WHERE id=?",
                      ("approved" if action == "approve" else "denied", now, resolved_by, request_id))
            return {"requestId": request_id, "status": "approved" if action == "approve" else "denied",
                    **result}


def ticket_redeem_grant(login_id, reward_type, reward_id, reward_amount, reward_name, now=None):
    """Spend one portal ticket and put one curated reward in the player's mailbox.

    Both the wallet and the game save live in this database. Keeping their updates
    in the same transaction is essential: a portal request must never consume a
    ticket without a mail, nor leave a mail that was not paid for. The caller has
    already matched the reward to the portal's fixed catalog; this function owns
    the persistence and accounting invariants.
    """
    login_id = str(login_id or "")
    reward_type = str(reward_type or "")
    reward_name = str(reward_name or "").strip()
    try:
        reward_id, reward_amount = int(reward_id), int(reward_amount)
    except (TypeError, ValueError):
        raise ValueError("invalid grant reward")
    if not login_id or not reward_type or not reward_name or reward_amount < 1:
        raise ValueError("invalid grant reward")
    now = time.time() if now is None else now
    with write_lock():
        with _conn() as c:
            account = c.execute("SELECT uid FROM accounts WHERE login_id=?", (login_id,)).fetchone()
            if not account:
                raise ValueError("game account is no longer available")
            uid = account[0]
            row = c.execute("SELECT data FROM players WHERE uid=?", (uid,)).fetchone()
            if not row:
                raise ValueError("enter the game before claiming a portal reward")
            balance, _last, _day, earned_today = _ticket_wallet(c, login_id, now)
            if balance < 1:
                raise TicketUnavailable("insufficient_tickets")

            st = json.loads(row[0])
            post_id = _append_portal_mail(
                st, "Phần thưởng Player Portal",
                f"Bạn đã dùng 1 ticket để nhận {reward_name} x{reward_amount}.",
                reward_type, reward_id, reward_amount)
            st["uid"] = uid
            c.execute("UPDATE ticket_wallets SET balance=? WHERE login_id=?",
                      (balance - 1, login_id))
            c.execute("INSERT INTO ticket_log(login_id,delta,reason,provider,event_id,ip,created) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (login_id, -1, "grant", None, None, None, now))
            c.execute("UPDATE players SET data=?, updated=? WHERE uid=?",
                      (json.dumps(st, ensure_ascii=False), now, uid))
            try:
                _write_derived(c, uid, st)
            except Exception as e:
                _derived_warn(e)
            return {"postId": post_id, "rewardName": reward_name,
                    **_ticket_snapshot(balance - 1, _last, earned_today, now)}


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
            uid = st.get("uid") or "dev-0001"
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

    # --- Friendly Battle lobbies
    lobby_create("TEST01", "a")
    lobby_create("TEST02", "b")
    L = lobby_get("TEST01")
    assert L and L["host_uid"] == "a" and L["members"] == ["a"]
    assert lobby_get("NONEXIST") is None
    assert lobby_join("TEST01", "c") is True
    L = lobby_get("TEST01")
    assert "c" in L["members"]
    assert lobby_get_by_uid("c")["code"] == "TEST01"
    # host leaves → lobby deleted
    lobby_leave("TEST01", "a")
    assert lobby_get("TEST01") is None
    # non-host leaves → player removed, lobby stays
    lobby_join("TEST02", "d")
    lobby_leave("TEST02", "d")
    L = lobby_get("TEST02")
    assert "d" not in L["members"]
    # full lobby
    for ch in "efg":
        lobby_join("TEST02", ch)
    assert lobby_join("TEST02", "zzz") is False  # 4 members = full
    lobby_leave_by_uid("b")  # host leaves → lobby gone
    assert lobby_get("TEST02") is None

    s = stats()
    assert s["schema_version"] == SCHEMA_VERSION and s["players"] >= 1, s
    vacuum()
    if IS_PG:
        with _conn() as _c:                    # leave the test database as we found it
            for t in ("lobbies", "player_items", "player_cards", "admin_sessions", "admins",
                      "sessions", "accounts", "players", "meta"):
                _c.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    else:
        os.remove(DB_PATH)
    print(f"playerdb self-check ok ({s['backend']}, schema v{SCHEMA_VERSION}, "
          f"{len(MIGRATIONS)} migrations)")
