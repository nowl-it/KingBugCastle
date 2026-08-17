"""Is this server safe to expose to the internet?

One command, run before `serve_public.sh`. FAIL means do not expose - each one is a
way the deployment gets owned, emptied, or knocked over. WARN means it will work but
something is worth knowing.

    python3 preflight.py            # check, exit 1 on any FAIL
    python3 preflight.py --strict   # exit 1 on warnings too

`serve_public.sh` runs this automatically; it exists separately so an operator can ask
the question without starting anything.
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER = ROOT.parent
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

FAIL, WARN, OK = "FAIL", "WARN", "ok"
_results = []


def check(level, what, detail=""):
    _results.append((level, what, detail))


def _env(name):
    return os.environ.get(name) or ""


# --- who can touch the admin surface ----------------------------------------
def check_admin_credentials():
    import playerdb
    playerdb.init()
    admins = playerdb.admin_count()
    if not admins:
        check(FAIL, "admin surface is unprotected",
              "/admin can rewrite or delete any save, and the loopback fallback is "
              "not protection behind a proxy. Fix: python3 dashboard.py --create-admin <user>")
        return
    check(OK, f"{admins} dashboard admin account(s)")


def check_dev_backdoors():
    if _env("GLOGIN_DEV") == "1":
        check(WARN, "GLOGIN_DEV=1",
              "/glogin hands a session to ANY account id it is asked for - anyone can "
              "log into anyone's save. Left on for public testing.")
    else:
        check(OK, "no dev login bypass")

    if _env("KGC_ADOPT_LONE_SAVE") == "1":
        check(FAIL, "KGC_ADOPT_LONE_SAVE=1",
              "the next login to reach this server inherits an existing unbound save. "
              "That is a one-shot migration switch, not a deployment setting.")
    else:
        check(OK, "lone-save adoption off")

    if _env("KGC_MULTIPLAYER") == "0":
        check(FAIL, "KGC_MULTIPLAYER=0",
              "single-player mode routes EVERY account to the same save; the first "
              "two players to log in would share one inventory.")
    else:
        check(OK, "multi-account identity on")


# --- abuse limits ------------------------------------------------------------
def check_limits():
    import server
    if server.RATE_LIMIT <= 0:
        check(WARN, "request rate limit disabled (KGC_RATE_LIMIT=0)",
              "one client can drive the state lock as fast as it can send")
    else:
        check(OK, f"rate limit {server.RATE_LIMIT} req/{server.RATE_WINDOW}s per address")

    check(OK, f"max body {server.MAX_BODY:,} bytes")
    check(OK, f"max players {server.MAX_PLAYERS}, "
              f"{server.NEW_PLAYER_PER_IP} new saves/IP/{server.NEW_PLAYER_WINDOW}s")

    if not server.TRUST_PROXY:
        check(WARN, "KGC_TRUST_PROXY unset",
              "behind Cloudflare Tunnel/nginx every request looks like 127.0.0.1, so "
              "all per-IP limits share ONE bucket. Set it to 1 if - and only if - a "
              "proxy is the only way in.")
    else:
        check(OK, "trusting forwarded client IP (proxy deployment)")


# --- data ---------------------------------------------------------------------
def check_state_store():
    import playerdb
    st = playerdb.stats()
    if st["schema_version"] != playerdb.SCHEMA_VERSION:
        check(FAIL, f"database at schema v{st['schema_version']}, code expects "
                    f"v{playerdb.SCHEMA_VERSION}", "run: python3 playerdb.py --migrate")
    else:
        check(OK, f"{st['backend']} schema v{st['schema_version']}, "
                  f"{st['players']} player(s), {st['admins']} admin(s)")

    db = playerdb.DB_PATH
    if not os.access(db.parent, os.W_OK):
        check(FAIL, f"{db.parent} is not writable", "every save would fail")
    backups = sorted((db.parent / "backups").glob("players-*.db"),
                     key=lambda p: p.stat().st_mtime)      # names are not all sortable
    if not backups:
        check(WARN, "no database backup exists yet",
              "run: python3 playerdb.py --backup   (and put it in cron)")
    else:
        check(OK, f"{len(backups)} backup(s), newest {backups[-1].name}")

    free = shutil.disk_usage(db.parent).free
    if free < 500 * 1024 * 1024:
        check(WARN, f"only {free / 1e6:.0f} MB free on the state volume",
              "backups and WAL need room")


def check_master_data():
    import config
    xml = config.XML_DIR
    missing = [n for n in ("Units.xml", "Skills.xml", "Strings_EN_US.xml")
               if not (xml / n).exists()]
    if missing:
        check(FAIL, f"master data incomplete in {xml}", f"missing: {', '.join(missing)}")
    else:
        check(OK, f"master data {xml.name} ({len(list(xml.iterdir()))} files)")

    cdn = SERVER / "real_cdn"
    hashes = cdn / "AssetHash.txt"
    if not hashes.exists():
        check(FAIL, "real_cdn/AssetHash.txt missing",
              "the client's patch-set check fails and it never leaves the loading screen")
        return
    listed = [ln.split(":")[0] for ln in hashes.read_text().split() if ":" in ln]
    absent = [n for n in listed if not (cdn / n).exists()]
    if absent:
        check(FAIL, f"CDN bundles listed but not present: {', '.join(absent)}")
    else:
        check(OK, f"CDN serving {len(listed)} bundle(s)")


def check_tls():
    have = (SERVER / "cert.pem").exists() and (SERVER / "key.pem").exists()
    if have:
        check(OK, "cert.pem/key.pem present (:8443)")
    else:
        check(WARN, "no cert.pem/key.pem",
              "fine behind a tunnel that terminates TLS; required for IP/LAN hosting "
              "because the client dials :443")


def check_route_coverage():
    from cli import route_coverage
    r = route_coverage.report()
    n = len(r["client_routes"])
    if r["bare"]:
        check(WARN, f"{len(r['bare'])} of {n} client routes have no handler",
              "they answer a generic model - those features do nothing")
    else:
        check(OK, f"all {n} client routes answered")


CHECKS = [check_admin_credentials, check_dev_backdoors, check_limits,
          check_state_store, check_master_data, check_tls, check_route_coverage]


def main(strict=False):
    for fn in CHECKS:
        try:
            fn()
        except Exception as e:
            check(FAIL, f"{fn.__name__} could not run", f"{type(e).__name__}: {e}")

    width = max(len(w) for _, w, _ in _results)
    for level, what, detail in _results:
        mark = {OK: "  ok  ", WARN: " WARN ", FAIL: " FAIL "}[level]
        print(f"[{mark}] {what.ljust(width)}  {detail}" if detail else f"[{mark}] {what}")

    fails = sum(1 for l, _, _ in _results if l == FAIL)
    warns = sum(1 for l, _, _ in _results if l == WARN)
    print()
    if fails:
        print(f"{fails} blocking problem(s) - do NOT expose this server yet.")
        return 1
    if warns and strict:
        print(f"{warns} warning(s), --strict.")
        return 1
    print(f"ready to expose ({warns} warning(s))" if warns else "ready to expose")
    return 0


if __name__ == "__main__":
    sys.exit(main(strict="--strict" in sys.argv))
