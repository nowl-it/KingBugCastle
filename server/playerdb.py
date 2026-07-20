"""SQLite-backed player state.

Replaces state/player.json + state/players/*.json. Why: the JSON files were read
and written by BOTH uvicorn processes (:8080 and :8443) with only a
threading.Lock guarding them, which locks nothing across processes - so a
concurrent write lost the other side's update or left a half-written file.
SQLite in WAL mode gives cross-process locking and atomic commits for free, and
one row per uid is what multi-player needs anyway.

The stored value is still the same JSON blob, so game logic is untouched.
"""
import contextlib, fcntl, json, sqlite3, time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "state" / "players.db"

# ponytail: fresh connection per call, no pool. Sub-ms at this request rate; add
# a threading.local cache only if profiling ever says connect() matters.
def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10.0)
    c.execute("PRAGMA journal_mode=WAL")     # concurrent readers + one writer, across processes
    c.execute("PRAGMA busy_timeout=10000")   # wait out the other process instead of raising
    return c

def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
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

def delete(uid):
    with _conn() as c:
        c.execute("DELETE FROM players WHERE uid=?", (uid,))

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
        c.execute("INSERT OR REPLACE INTO sessions (token, uid, created) VALUES (?,?,?)",
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
        c.execute("INSERT OR REPLACE INTO accounts (login_id, uid) VALUES (?,?)", (login_id, uid))

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
    Idempotent: does nothing once the table has rows."""
    init()
    if count():
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
    return n


if __name__ == "__main__":   # self-check: cross-process semantics we depend on
    import tempfile, os
    DB_PATH = Path(tempfile.mkdtemp()) / "t.db"
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
    assert sqlite3.connect(DB_PATH).execute(
        "SELECT data FROM players WHERE uid='c'").fetchone() is not None
    os.remove(DB_PATH)
    print("playerdb self-check ok")
