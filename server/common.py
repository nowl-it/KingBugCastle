"""Primitives every handler needs: the log buffer, time formatting, body coercion.

These lived in server.py, which meant a domain module could not use them without
importing server.py back - a cycle. They depend on nothing in this repo, so any
module can import them freely. That is what makes splitting handlers out of
server.py possible at all.

    python3 common.py     # self-check
"""
import datetime
import os
import re
import sys

# The dashboard's log view reads this through /admin/api/logs.
LOG_BUF = []

# One echoed line per request is right for a dev box and wrong for a server that runs
# for weeks - it is an unbounded file nobody rotates. KGC_QUIET=1 keeps the in-memory
# buffer (the dashboard's log view still works, it is capped) but stops the per-request
# echo. Events and errors always print.
QUIET = os.environ.get("KGC_QUIET") == "1"


def _record(args):
    msg = datetime.datetime.now().strftime("%H:%M:%S") + " " + " ".join(str(a) for a in args)
    LOG_BUF.append(msg)
    if len(LOG_BUF) > 500:
        LOG_BUF[:] = LOG_BUF[-400:]


def admin_log(*args):
    """An event worth keeping: a login, a limit trip, a failure."""
    _record(args)
    print(*args, file=sys.stderr)


def trace(*args):
    """Per-request chatter. Buffered always, echoed unless KGC_QUIET=1."""
    _record(args)
    if not QUIET:
        print(*args, file=sys.stderr)


def now_iso(delta_days=0, seconds=0):
    return (datetime.datetime.utcnow() + datetime.timedelta(days=delta_days, seconds=seconds)
            ).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def next_reset_iso(days=1):
    """Next UTC-midnight rollover boundary, `days` out.

    `tomorrow` / `nextWeek` are DERIVED, never served from stored state.
    Scene_Lobby.Update polls `if (now >= playerData.tomorrow_) FetchNextDay()`
    once a second, and FetchNextDay re-runs the whole login + lobby fetch chain.
    A stored value is frozen at account-creation time, so the check goes
    permanently true and the client re-logins at 1 Hz forever.
    """
    midnight = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight + datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def body_int(value, default=0, lo=None, hi=None):
    """A number out of a request body, as an int, within bounds.

    Request fields arrive as whatever the client's serialiser produced. A field
    that comes back as "2" instead of 2 makes `max(1, count)` raise TypeError and
    the route answers 500; a negative index reaches a Python list and quietly
    writes to the wrong end of it, which is worse than crashing. Both are read
    through here rather than guarded per handler."""
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def body_list(value, of=None):
    """A list field out of a request body. `of` filters/converts each element.

    A field the client sends as null, a bare number, or an object is not a list,
    and iterating it raises before the handler gets to validate anything."""
    if not isinstance(value, (list, tuple)):
        return []
    if of is None:
        return list(value)
    out = []
    for v in value:
        try:
            out.append(of(v))
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def body_str(value, default=""):
    return value.strip() if isinstance(value, str) else default


# --- date-shaped response fields ---------------------------------------------
# The client hands these to DateTime.Parse, which throws ArgumentNullException on
# null. Handlers fill the ones they compute; every other declared field on the same
# model keeps its `null` default, and a partial response (a chat refresh, a heart
# recover) then carries a dozen nulls belonging to fields it never touched. That is
# the shape of the `tomorrow` bug, which froze the lobby into a 1 Hz re-login storm.
#
# Naming is consistent across the whole API, so it can be decided from the name.
DATE_FIELD = re.compile(r"(At|Date|Dates|Time|Times)$"
                        r"|^(until|expired|created|updated|next|last)", re.I)
# "valid until X" - a past value reads as already-expired, and for `expiredAt` on a
# session that means the client re-logs in immediately. These get a future default.
DEADLINE_FIELD = re.compile(r"expired|until|end|^next", re.I)


def date_default(name, now_iso_fn):
    """What an unset date-shaped field should carry, or None if it is not one."""
    if not DATE_FIELD.search(name):
        return None
    return now_iso_fn(7) if DEADLINE_FIELD.search(name) else now_iso_fn(0)


if __name__ == "__main__":
    # The coercions are the whole point: every one of these used to 500 a route.
    assert body_int("2") == 2 and body_int(1.9) == 1
    assert body_int(None) == 0 and body_int("x", 7) == 7
    assert body_int(-5, lo=0) == 0 and body_int(99, hi=10) == 10
    assert body_int(True) == 1, "bool is an int in Python; do not special-case it"
    assert body_list(None) == [] and body_list(5) == [] and body_list({"a": 1}) == []
    assert body_list([1, "2", None], of=int) == [1, 2], "bad elements must be dropped"
    assert body_str("  x ") == "x" and body_str(None) == "" and body_str(5, "d") == "d"

    assert now_iso().endswith("Z") and "T" in now_iso()
    assert next_reset_iso(1).endswith("T00:00:00.000Z"), "must land on UTC midnight"
    assert next_reset_iso(7) > next_reset_iso(1)

    import io
    LOG_BUF.clear()
    _real_stderr, sys.stderr = sys.stderr, io.StringIO()
    for i in range(600):
        admin_log("line", i)
    echoed = sys.stderr.getvalue()
    sys.stderr = _real_stderr
    assert len(LOG_BUF) <= 500, f"log buffer unbounded: {len(LOG_BUF)}"
    assert LOG_BUF[-1].endswith("line 599")
    assert "line 599" in echoed, "an event must always reach stderr"

    # trace() must keep buffering when quiet, or the dashboard's log view goes blank
    # on exactly the deployment that needs it most.
    QUIET = True
    _real_stderr, sys.stderr = sys.stderr, io.StringIO()
    trace("quiet line")
    admin_log("loud line")
    echoed = sys.stderr.getvalue()
    sys.stderr = _real_stderr
    assert "quiet line" not in echoed, "KGC_QUIET=1 still echoed a request"
    assert "loud line" in echoed, "quiet mode silenced an event, not just chatter"
    assert LOG_BUF[-2].endswith("quiet line"), "quiet mode dropped it from the buffer"

    # Date defaults: a deadline must land in the FUTURE. `expiredAt` in the past is a
    # session the client considers dead, and it re-logs in immediately - the same
    # 1 Hz storm, arrived at from the other direction.
    assert date_default("gold", now_iso) is None
    assert date_default("name", now_iso) is None
    for n in ("expiredAt", "seasonUntilAtDate", "nextWeek", "eventEndAtDate",
              "clanRaidUntilAtDate", "eventPackageItemsUntilAt"):
        v = date_default(n, now_iso)
        assert v and v > now_iso(1), f"{n} defaulted to a past deadline: {v}"
    for n in ("serverTime", "createdAt", "lastHeartTime", "accountCreatedAt",
              "contractUntilAt"):
        assert date_default(n, now_iso), f"{n} was not recognised as a date field"
    assert date_default("lastHeartTime", now_iso) < now_iso(1), \
        "a 'last X' timestamp in the future is not a timestamp"
    print("common self-check ok")
