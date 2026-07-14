# Sharing King Bug Castle - one server, many players

You run ONE server. You hand out one `KingBugCastle.xapk`. Anyone installs it (no root, no
hosts edit, no adb) and plays against your server. This works because the build **bakes your
server address into the APK** (`patch_hosts.py` rewrites the 5 hardcoded backend hostnames in
`global-metadata.dat`), so every device talks to you instead of Awesomepiece - the same
all-hosts-to-one-server trick the local `/etc/hosts` + `adb reverse` setup uses, but frozen
into the file so remote players need zero config.

## 1. Pick how your server is reachable

Players' phones must reach your machine at the baked host on **port 443 (https)**. The
SSL-bypass patch makes the client accept any cert, so a self-signed cert is fine. Three ways,
easiest first:

| Option | What you need | Baked host |
|---|---|---|
| **A. Cloudflare Tunnel** (recommended) | a domain you own + `cloudflared`; run a NAMED tunnel to `http://localhost:8080` | `kgc.yourdomain.com` (≤26 chars) |
| **B. Public IP + port-forward** | static/public IP, forward external `443` → your box `8443` | `203.0.113.7` (your IP) |
| **C. LAN only** | same Wi-Fi; forward `443`→`8443` on your box | your LAN IP e.g. `192.168.1.50` |

**Host constraint:** ≤ **26 characters**, bare host only (no `https://`, no port, no path). An
IPv4 always fits; a domain must be short. No port means the client uses 443 - expose 443.

> Cloudflare quick tunnels (`cloudflared tunnel --url ...`) hand out a long random
> `*.trycloudflare.com` that changes each run and exceeds 26 chars - use a **named** tunnel with
> your own short subdomain instead so the host is stable and short.

## 2. Build the shareable XAPK

```bash
# bake your host in and package KingBugCastle.xapk (no device needed)
SHARE_HOST=kgc.yourdomain.com python3 server/rebuild_arm64_mod.py --share
#   or:  python3 server/rebuild_arm64_mod.py --share --host 203.0.113.7
```

Output: `KingBugCastle.xapk` at the repo root. Same 12 SSL/NRE patches + XIGNCODE stub as the
normal build, renamed to `com.nowl.castle` (installs beside the real game). Hand this file to
players with `README_PLAYER.md`.

## 3. Run the server

```bash
cd server && ./serve_public.sh        # HTTP :8080  +  HTTPS :8443 (0.0.0.0)
python3 server/dashboard.py           # admin + battle tracker -> http://localhost:8081
```

- **Cloudflare Tunnel**: point the named tunnel at `http://localhost:8080`; Cloudflare does TLS.
- **IP / LAN**: forward external `443` → local `8443` (e.g. `socat TCP-LISTEN:443,fork TCP:127.0.0.1:8443`, or a router rule).

Player saves live in `server/state/`. Manage currency / mail / rewards from the dashboard
(Admin tab) - see `server/README.md`.

## 4. Verify it actually reaches you (do this once)

Backend hostnames appear twice in the metadata: as runtime string literals (rebound - the copies
the client uses) and as vestigial field-default metadata (2 copies of infra/cdn left as-is).
Confirm the runtime path really hits your server: with `serve_public.sh` running, install the
XAPK on a test device that is NOT on your LAN (mobile data, or a friend), launch, and check the
server log shows `POST /auth/login` and `GET /patch/...` from that device. If the client instead
tries the real `*.awesomepiece.com`, the boot hangs - tell me and the field-default copies get
patched too.

## When the host changes

Rebuild + reshare - the address is frozen in the file:

```bash
SHARE_HOST=<new-host> python3 server/rebuild_arm64_mod.py --share
```

Players reinstall the new `.xapk` over the old one.
