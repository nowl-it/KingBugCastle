"""SQLite store for the coupon auto-redeem bot.

The `redemptions` table is the single source of truth for "has this account
used this code yet": a pair is attempted exactly once, because the site's
"invalid or has already been used" does not distinguish a wrong code from an
already-redeemed one (see plans/coupon-autoredeem/01-core.md).

Every public helper opens its own connection (WAL mode) so the worker cycle,
the dashboard thread and tests can share the module without sharing a handle.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVER = os.path.dirname(_HERE)
DEFAULT_DB = os.path.join(_SERVER, "state", "coupons.db")
RAW_DIR = os.path.join(_SERVER, "state", "coupon_raw")

# COUPON_DB keeps tests (tmp) and any future multi-instance setup off the
# production file without threading a path argument through every call.
DB_PATH = os.environ.get("COUPON_DB") or DEFAULT_DB


def lock_path() -> str:
    """Cycle lock lives beside the DB, so a test DB never fights the real one."""
    return DB_PATH + ".lock"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  uid         TEXT PRIMARY KEY,
  label       TEXT NOT NULL DEFAULT '',
  enabled     INTEGER NOT NULL DEFAULT 1,
  added_at    REAL NOT NULL,
  last_run_at REAL,
  last_result TEXT
);

CREATE TABLE IF NOT EXISTS codes (
  code         TEXT PRIMARY KEY,
  first_seen_at REAL NOT NULL,
  source       TEXT NOT NULL,
  source_text  TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'new'
);

-- One row per (uid, code): "this account already tried this code".
CREATE TABLE IF NOT EXISTS redemptions (
  uid     TEXT NOT NULL,
  code    TEXT NOT NULL,
  status  TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  at      REAL NOT NULL,
  PRIMARY KEY (uid, code)
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at REAL,
  finished_at REAL,
  found_codes INTEGER DEFAULT 0,
  new_codes INTEGER DEFAULT 0,
  attempted INTEGER DEFAULT 0,
  ok INTEGER DEFAULT 0,
  failed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

_LOCK = threading.Lock()


def connect(path: str | None = None) -> sqlite3.Connection:
    db = path or DB_PATH
    parent = os.path.dirname(db)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(path: str | None = None) -> None:
    with _LOCK, connect(path) as conn:
        conn.executescript(SCHEMA)


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# --- accounts ---------------------------------------------------------------

def add_account(uid: str, label: str = "", path: str | None = None) -> bool:
    """Register a Player-ID. Returns True when the row is new."""
    uid = (uid or "").strip()
    if not uid:
        raise ValueError("empty uid")
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO accounts (uid, label, added_at) VALUES (?, ?, ?)",
            (uid, label.strip(), time.time()),
        )
        return cur.rowcount > 0


def set_account_enabled(uid: str, enabled: bool, path: str | None = None) -> bool:
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            "UPDATE accounts SET enabled=? WHERE uid=?", (1 if enabled else 0, uid)
        )
        return cur.rowcount > 0


def accounts(enabled_only: bool = True, path: str | None = None) -> list[dict]:
    q = "SELECT * FROM accounts"
    if enabled_only:
        q += " WHERE enabled=1"
    q += " ORDER BY added_at, uid"
    with _LOCK, connect(path) as conn:
        return _rows(conn.execute(q))


def account(uid: str, path: str | None = None) -> dict | None:
    with _LOCK, connect(path) as conn:
        row = conn.execute("SELECT * FROM accounts WHERE uid=?", (uid,)).fetchone()
        return dict(row) if row else None


# --- codes ------------------------------------------------------------------

def add_code(code: str, source: str, source_text: str = "", path: str | None = None) -> bool:
    """Insert a coupon code. Returns True when it was not already known."""
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("empty code")
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO codes (code, first_seen_at, source, source_text)"
            " VALUES (?, ?, ?, ?)",
            (code, time.time(), source, source_text[:2000]),
        )
        return cur.rowcount > 0


def set_code_status(code: str, status: str, path: str | None = None) -> None:
    with _LOCK, connect(path) as conn:
        conn.execute("UPDATE codes SET status=? WHERE code=?", (status, code))


def codes(path: str | None = None) -> list[dict]:
    with _LOCK, connect(path) as conn:
        return _rows(conn.execute("SELECT * FROM codes ORDER BY first_seen_at DESC, code"))


def open_codes(path: str | None = None) -> list[dict]:
    """Codes still worth trying - `invalid`/`expired` are global, stop on them."""
    with _LOCK, connect(path) as conn:
        return _rows(
            conn.execute(
                "SELECT * FROM codes WHERE status NOT IN ('invalid', 'expired')"
                " ORDER BY first_seen_at, code"
            )
        )


# --- redemptions ------------------------------------------------------------

def needs_attempt(uid: str, code: str, path: str | None = None) -> bool:
    with _LOCK, connect(path) as conn:
        row = conn.execute(
            "SELECT 1 FROM redemptions WHERE uid=? AND code=?", (uid, code)
        ).fetchone()
        return row is None


def record_redemption(uid: str, code: str, status: str, message: str = "",
                      path: str | None = None) -> bool:
    """Persist one attempt. Never overwrites - the first result is the truth."""
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO redemptions (uid, code, status, message, at)"
            " VALUES (?, ?, ?, ?, ?)",
            (uid, code, status, message[:1000], time.time()),
        )
        if cur.rowcount:
            conn.execute(
                "UPDATE accounts SET last_run_at=?, last_result=? WHERE uid=?",
                (time.time(), status, uid),
            )
        return cur.rowcount > 0


def redemption(uid: str, code: str, path: str | None = None) -> dict | None:
    with _LOCK, connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM redemptions WHERE uid=? AND code=?", (uid, code)
        ).fetchone()
        return dict(row) if row else None


def matrix(path: str | None = None) -> dict[str, dict[str, str]]:
    """{uid: {code: status}} for the dashboard grid."""
    with _LOCK, connect(path) as conn:
        out: dict[str, dict[str, str]] = {}
        for r in conn.execute(
            "SELECT uid, code, status FROM redemptions ORDER BY at"
        ).fetchall():
            out.setdefault(r["uid"], {})[r["code"]] = r["status"]
        return out


# --- runs / meta ------------------------------------------------------------

def start_run(path: str | None = None) -> int:
    with _LOCK, connect(path) as conn:
        cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (time.time(),))
        return int(cur.lastrowid)


def finish_run(run_id: int, *, found=0, new=0, attempted=0, ok=0, failed=0,
               path: str | None = None) -> None:
    with _LOCK, connect(path) as conn:
        conn.execute(
            "UPDATE runs SET finished_at=?, found_codes=?, new_codes=?, attempted=?,"
            " ok=?, failed=? WHERE id=?",
            (time.time(), found, new, attempted, ok, failed, run_id),
        )


def last_run(path: str | None = None) -> dict | None:
    with _LOCK, connect(path) as conn:
        row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def meta_get(key: str, default: str | None = None, path: str | None = None) -> str | None:
    with _LOCK, connect(path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def meta_set(key: str, value: str, path: str | None = None) -> None:
    with _LOCK, connect(path) as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# --- raw responses ----------------------------------------------------------

def save_raw(html: str, uid: str, code: str) -> str:
    """Keep an unrecognised site response for calibration (see 00-recon.md)."""
    os.makedirs(RAW_DIR, exist_ok=True)
    safe_uid = "".join(c for c in uid if c.isalnum() or c in "-_") or "unknown"
    safe_code = "".join(c for c in code if c.isalnum() or c in "-_") or "unknown"
    path = os.path.join(RAW_DIR, f"{int(time.time())}_{safe_uid}_{safe_code}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path
