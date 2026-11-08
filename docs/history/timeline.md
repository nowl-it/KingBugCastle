# Project timeline - King God Castle private server

A dated record of how the project moved from "can I read this game's data?" to a
publicly hosted private server with its own client builds, a dashboard, a wiki and a
strategy compendium.

Numbers here are pulled from `docs/history/stats.json` (harvested from five agent
transcripts), `git log`, and the commits themselves.

- **Sessions:** 283 · **Turns:** 44,940 · **Input tokens:** 533.1 M · **Output tokens:** 16.3 M
- **Commits:** 672 recorded - 2026-07: 93, 08: 264, 09: 284, 10: 24, 11: 7
- **First session:** 2026-03-25 · **Last session harvested:** 2026-11

---

## Phase 0 - Data archaeology (March-June 2026)

| Date | Milestone |
|---|---|
| 2026-03-25 | First agent session in the `KGCentral` monorepo - the workspace that later becomes `kgc`. |
| 2026-04 | Master-data digging: `Strings_*.xml`, unit/skill tables, sprite atlases. Everything starts with reading XML, not with running code. |
| 2026-05 | Client asset extraction (UnityPy) - portraits, item icons, sprites, bundles. |
| 2026-06-25 | Notification/monitor scaffolding: version watcher, notice fetcher, ntfy topics across 15 languages. The first piece of "keep the player informed" tooling. |
| 2026-06-26 | **First private-server boot.** FastAPI on `:8080`, a hand-written `route_models.json` heuristic, and a client patched to talk to it. |

The pattern for the entire project was set here: *client is the specification, XML is
the schema, anything you cannot read is a patch target.*

## Phase 1 - Making the client believe (July 2026)

| Date | Milestone |
|---|---|
| 2026-07-05 | `xml.bak` vs `xml_live` diffing; Cathy (10800-10810) master-data alignment; the `Inherit=` bug chain. |
| 2026-07-06 | `Initial commit` - docs, clean architecture, the repo becomes presentable. |
| 2026-07-14 | Operator docs + skin/treasure/training-dummy tooling; portable self-host. |
| 2026-07-16 | **v171 il2cpp extraction.** v171 ships no on-disk `libil2cpp.so`: XIGNCODE NEO packs and encrypts it inside the packer `.so`. Unpack recipe becomes `docs/mftl-extraction.md`. |
| 2026-07-19 | The corrupt-`.so` incident: 21 stray bytes including a `b` that overwrote `mov w8,#-2` inside a `MoveNext` state machine → infinite UniTask recursion → stack overflow on "Loading resources". Misdiagnosed twice as an IL2CPP bug before being traced to hand-patching. Rule adopted: **never hand-patch the shipped lib**. |
| 2026-07-24 | Route coverage sprint: every v171 client route mapped to its real response model, plus shop, missions, territory, Babel, colosseum, attendance, clan, cosmetics, invasion rewards. |
| 2026-07-25 | 100% of client routes answered; save transfer between devices; runs that survive app close; leaderboards; rate limiter can no longer allocate until the process dies. |
| 2026-07-26 | **Google login web-bridge**: native hook opens `/glogin`, poller retrieves the account id and calls `Scene_Login.Auth`. Multi-account becomes the default. |
| 2026-07-27 | CI/CD workflow builds the XAPK automatically. Black-lobby NRE traced to `ldr → mov` klass patches - the theory behind them was disproven, the patches stay off. |
| 2026-07-31 | **Public OCI deploy** behind `kingbugcastle.id.vn`: Ubuntu 20.04, Python 3.12 via python-build-standalone, HTTP `:8080` + TLS `:8443`, host firewall + NAT. The zero-cost mandate is stated here: nothing may cost money. |

## Phase 2 - From "somebody's server" to a service (August 2026)

| Date | Milestone |
|---|---|
| 2026-08-01 | GitHub Actions: `ci.yml` (full pytest suite), `deploy.yml` (restricted command-only deploy key), `build-xapk.yml` (release pipeline). |
| 2026-08-01 | Awakening `potentialTier` semantics decoded: one tier, `0` = unawakened. The default save had seeded `1`, so every fresh hero showed a star it should not have. |
| 2026-08-07 | Daily-reset bug: stored `tomorrow` made the client re-login at 1 Hz forever - 17 requests/second, no exception, nothing in logcat. `tomorrow` is now always derived. |
| 2026-08-08 | Dimension-hero gacha fix: `overcome` starts at 1, duplicates increment it, and `cardExpResults` is mandatory or the client shows stale stars until restart. |
| 2026-08-13 | **v172.0.01 port.** Firebase `LogEvent` inside `Web.Get` was killing the HTTP callback mid-flight on a device without Play Services - stubbed both overloads. New offsets, new patches, ranking endpoint redirected to loopback. |
| 2026-08-14 | Leaderboard architecture: weekly combat-power score travels inside `/game/complete` as `eliteRankingScore`; server stores the best value. |
| 2026-08-17 | Altar/building points: two keys (`buildingPoint` / `buildingPoints`) collapsed into one, clamped at zero. |
| 2026-08-18 | Auth hardening: id-less logins are refused in multiplayer; the template `uid` can never become a save key. `GET /auth` mints a token so a fresh install can actually log in. Accessory sub-stats merge per key. |
| 2026-08-20 | **Frieren skin pipeline.** Not a new XML row: clone texture + 19 sprites + prefab + 10 animation clips + the illustration, give the sprites a distinct render-data key, and add five Addressables locations. Also forces asset-bundle CRC to zero at four runtime sites. |
| 2026-08-28 | Player portal on Caddy + Cloudflare. |
| 2026-08-31 | Dominion blacksmith. |

## Phase 3 - Beyond the game (September 2026)

| Date | Milestone |
|---|---|
| 2026-09-05 | Wiki + PR workflow. |
| 2026-09-08 | Master-data republish diffed against the previous bundle and published as an illustrated HTML report. |
| 2026-09-09 | Dimension-sync fix (the feature existed but silently did nothing). |
| 2026-09-12 | v173 client bump; the "il2cpp hangs waiting for a keypress" process trap is written into the docs so it stops costing tokens. |
| 2026-09-14 | Farael skill range anomaly found in official master data (range 3 → 41 tiles by level 3) - read-only investigation, no fix. |
| 2026-09-15 | **Strife Compendium**: every strategy, tarot, mutual-exclusion rule and roll-probability simulator, built as a single bilingual HTML file and pushed to GitHub Pages. |

## Phase 4 - Reconstruction (October 2026)

| Date | Milestone |
|---|---|
| 2026-10 | Ghidra + Unity project reconstruction work: whole-game source recovery for deeper debugging, plus a CDN monitor and Discord integration. |
| 2026-10-25 | Dashboard redesign - audit log, raid admin, log tail, light/dark theme. Clan Raid for v174.1.00 completed and the client bumped. |
| 2026-10-27 | Local loopback builds default to the *King Local Castle* label so local and public installs are distinguishable on device. |

## Phase 5 - Wrap-up (November 2026)

| Date | Milestone |
|---|---|
| 2026-11-04 | Deploy fix: the Caddy sync path that shipped as a 502. |
| 2026-11-07 | Cleanup and handoff: chat history harvested from five agent stores, repository cleaned of build junk, docs rewritten, bilingual blog written. |

---

## What the arc looks like

Three shifts account for almost all of the progress:

1. **Read before patching.** Nearly every multi-session rabbit hole began with a patch
   applied to a symptom. Nearly every fix began with decompiling the real function.
2. **Derive, never store.** `tomorrow`, master-data gates, CRC, offsets - anything copied
   into state goes stale and then loops, crashes, or lies.
3. **One key, one path.** Altar points, accessory sub-stats, auth fallbacks: duplicated
   representations caused every one of those incidents.

See `docs/history/lessons.md` for the trap ledger, and `docs/blog/` for the narrative version.
