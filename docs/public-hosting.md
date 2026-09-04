# Hosting this server publicly

`SHARE.md` covers building the shareable XAPK. This covers running the server it
points at, on a box strangers can reach.

The one-line version:

```bash
cd server
python3 dashboard.py --create-admin <username>   # once
python3 preflight.py                              # must print "ready to expose"
./serve_public.sh
```

`serve_public.sh` runs `preflight.py` itself and refuses to start on any FAIL.

For the public OCI deployment, keep `/etc/kgc/server.env` readable only by the
service operator (for example `chmod 600`). It must contain the generated OAuth state
key and the version-aligned route metadata location:

```sh
GLOGIN_STATE_SECRET=<generated-random-value>
KGC_IL2CPP_SCRIPT_JSON=/home/ubuntu/kgc/il2cpp/v172.0.01/script.json
# Caddy is the sole app ingress (both public hostname and origin-IP routes):
KGC_TRUST_PROXY=1
KGC_BIND_HOST=127.0.0.1
```

`serve_public.sh` and `deploy_hook.sh` load this file automatically. The metadata is
an extracted proprietary artifact and is intentionally not stored in git; deployment
must provision it from the exact client version before preflight can pass.

## Domain and origin-IP clients

`systemd/kgc-public.Caddyfile` serves the game on both
`kingbugcastle.id.vn` and `213.35.110.245`.  This is intentional: a public XAPK can
bake either value as `share_host`, while its native Google poller uses the origin IP
on plain HTTP port 80.  In the Build & Release XAPK workflow use:

```text
share_host: kingbugcastle.id.vn   # or 213.35.110.245
glogin_host: kingbugcastle.id.vn
glogin_poll_host: 213.35.110.245
glogin_poll_port: 80
```

The IP virtual hosts remove incoming Cloudflare/forwarded-IP headers and set their
own client address. The domain virtual host accepts only Cloudflared's private Docker
bridge before retaining `CF-Connecting-IP`. Keep the app loopback-bound with
`KGC_TRUST_PROXY=1`; exposing :8080/:8443 directly would make those headers forgeable.

---

## The threat model

Players are not authenticated at the transport level and cannot be: the client picks
its own account id and presents it. That is fine - every save is a god account by
design, so there is nothing to steal by cheating. What actually matters:

| Risk | What stops it |
|---|---|
| A stranger rewrites or deletes saves via `/admin/api/*` | `guard_admin` - token, admin session, or loopback (see below) |
| A request with **no token** lands on another player's save | multiplayer `load_state()` hands it a throwaway save; it used to fall back to `playerdb.active()`, i.e. whatever the dashboard had selected (fixed 2026-07-31, `test_public_hardening`) |
| A stranger consumes another player's Google sign-in handoff | `GLOGIN_DEV` must be unset; pending handoffs are one-time and source-address-bound |
| One client fills the disk with saves | `KGC_MAX_PLAYERS`, `KGC_NEW_PLAYER_PER_IP` |
| One client OOMs the box with a huge POST | `KGC_MAX_BODY`, enforced on declared *and* chunked bodies |
| One client starves everyone else | `KGC_RATE_LIMIT` per address |
| A handler bug 500s and the client hangs on Loading | handler exceptions are contained; the route answers its empty model |
| Losing everyone's progress | automatic backups, `KGC_BACKUP_HOURS` |

## Loopback is not a security boundary here

This is the single most important thing on the page.

Behind a **Cloudflare Tunnel, nginx, Caddy, or any port-forward that rewrites the
source address**, every request arrives from `127.0.0.1`. Any rule of the form "allow
loopback" therefore means "allow the entire internet".

Two consequences:

1. **`/admin` refuses the loopback fallback as soon as a real credential exists.**
   Set `KGC_ADMIN_TOKEN` *or* create a dashboard account, and loopback stops being a
   way in - on both `:8080` and the dashboard. With neither configured, loopback is
   allowed and preflight FAILs, because that combination is only safe on a machine
   nobody else can reach.

2. **Per-IP limits collapse into one bucket.** Every player looks like the same
   address, so `KGC_NEW_PLAYER_PER_IP=5` becomes five new accounts per hour for the
   whole server. Fix by setting `KGC_TRUST_PROXY=1`, which reads `cf-connecting-ip` /
   `x-forwarded-for` instead. Only set it when a proxy is the **sole** way in: if
   anyone can reach the port directly, they can forge the header and reset every
   limit at will. `serve_public.sh` enforces that pairing: run the game listeners
   on loopback too, e.g. `KGC_TRUST_PROXY=1 KGC_BIND_HOST=127.0.0.1 ./serve_public.sh`.
   Keep the default `KGC_BIND_HOST=0.0.0.0` for a direct-IP deployment and leave
   `KGC_TRUST_PROXY` unset.

## Settings

| Variable | Default | What it does |
|---|---|---|
| `KGC_ADMIN_TOKEN` | unset | Shared secret for `/admin` and the dashboard. An admin account is better - it can be rotated per operator and does not end up in URLs and logs. |
| `KGC_TRUST_PROXY` | unset | Read the forwarded client IP. **Only behind a proxy.** |
| `KGC_RATE_LIMIT` | `600` | Requests per address per window; `0` disables. CDN `/patch/` is exempt (a first launch pulls six bundles back to back). |
| `KGC_RATE_WINDOW` | `60` | Seconds. |
| `KGC_MAX_BODY` | `1000000` | Bytes. The real client's largest body is a roguelike blob, a few KB. |
| `KGC_MAX_PLAYERS` | `200` | Hard cap on saves. |
| `KGC_NEW_PLAYER_PER_IP` | `5` | New saves per address per `KGC_NEW_PLAYER_WINDOW` (3600s). |
| `KGC_BACKUP_HOURS` | `24` | Automatic database backup interval; `0` disables. |
| `KGC_MULTIPLAYER` | `1` | Must stay on. `0` routes every account to one shared save. |
| `KGC_ADOPT_LONE_SAVE` | unset | One-shot migration switch. Never set it on a public server: the next login inherits an existing unbound save. |
| `GLOGIN_DEV` | unset | Dev login bypass. Hands a session to any account id asked for. |

## Backups

Automatic, in-process, every `KGC_BACKUP_HOURS` into `server/state/backups/`, newest
10 kept. Both uvicorn processes run the timer; the due-check happens under the
cross-process write lock, so only one of them actually writes.

Manual:

```bash
python3 playerdb.py --backup [tag]      # take one now
python3 playerdb.py --stats             # players, sessions, schema version, size
python3 playerdb.py --purge-sessions    # drop expired logins
python3 playerdb.py --vacuum            # reclaim space
python3 playerdb.py --migrate           # apply pending schema migrations
```

Restoring is a file copy: stop the server, replace `state/players.db` with a backup,
start it. Delete `players.db-wal` / `players.db-shm` alongside it.

On PostgreSQL (`KGC_DB_URL`) the in-process backup steps aside - use `pg_dump`.

## Admin accounts

Easiest path: open the dashboard on the machine it runs on (where the loopback rung still
lets you in) and use the **Account** tab - it lists the accounts, says which guard rung is
currently live, and creates the first one. Creating it immediately closes loopback, so the
same browser is asked to sign in.

The CLI does the same thing without a browser:

```bash
python3 dashboard.py --create-admin <username>   # prompts for a password
python3 dashboard.py --list-admins
```

scrypt hashed, 12-hour sessions, httponly cookie, 10 sign-in attempts per 5 minutes.
The last remaining account cannot be deleted. The dashboard forwards the signed-in
operator's session when it proxies `/admin/api/*` to the game port, so one sign-in
covers both.

## Checks

```bash
python3 preflight.py            # is it safe to expose? exit 1 on any FAIL
python3 preflight.py --strict   # exit 1 on warnings too
python3 route_coverage.py       # every route the client calls, and who answers it
cd server && for t in tests/test_*.py; do python3 "$t" >/dev/null || echo "FAIL $t"; done
```

`tests/test_public_hardening.py` holds the deployment rules specifically - the admin
ladder, body caps, rate limit, and forwarded-IP handling.

## What is deliberately not defended

- **Cheating.** Every save starts as a god account; there is nothing to protect.
- **Account theft by guessing an id.** Guest ids are client-generated randoms. Whoever
  presents one gets that save - that is the design, and it is why a stable Google
  login exists. Do not log account ids; the server records an 8-character fingerprint.
- **Distributed floods.** Per-address limits are per process, in memory. A real DDoS
  needs Cloudflare in front, which the tunnel deployment already gives you.
