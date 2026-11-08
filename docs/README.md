# KGC Private Server - Operator Knowledge Base

Practical playbooks for **running and modifying** the King God Castle private server:
how to grant items, unlock content, build test stages, edit master data, and deploy
changes to a client. This is the *how-to-operate* layer.

<sub>🇻🇳 <a href="README.vi.md">Đọc bằng tiếng Việt</a></sub>

It complements the other docs - read those for the *why* and the *internals*:

| Doc | Scope |
|-----|-------|
| **[../HANDOVER.md](https://github.com/nowl-it/KingBugCastle/blob/main/HANDOVER.md)** | Taking over the project: day-1 checklist, the recurring job, the trap ledger, known debt |
| **[../README.md](https://github.com/nowl-it/KingBugCastle/blob/main/README.md)** | Project landing, feature list, repo layout |
| **[../SETUP.md](https://github.com/nowl-it/KingBugCastle/blob/main/SETUP.md)** | First-run: clone → `setup.py` → run your own server |
| **[../SHARE.md](https://github.com/nowl-it/KingBugCastle/blob/main/SHARE.md)** | Distribute a baked XAPK to remote players |
| **[../AGENTS.md](https://github.com/nowl-it/KingBugCastle/blob/main/AGENTS.md)** | ARM64 binary-patch inventory, RVA map, il2cpp internals |
| **[../KNOWLEDGE.md](https://github.com/nowl-it/KingBugCastle/blob/main/KNOWLEDGE.md)** | Datamine reference: API modules, IL2CPP, master-data files |
| **[../server/WORKFLOW.md](https://github.com/nowl-it/KingBugCastle/blob/main/server/WORKFLOW.md)** | Day-to-day edit/test/deploy loop, "which file do I edit" |

## This folder

| Playbook | Use it to |
|----------|-----------|
| **[deploy-and-run.md](deploy-and-run.md)** | Start the two servers, connect a device, push a change to the client |
| **[public-hosting.md](public-hosting.md)** | Run it where strangers can reach it: preflight, admin accounts, abuse limits, backups |
| **[dashboard-macros.md](dashboard-macros.md)** | Using the Next.js Admin Dashboard to quickly grant Macro Profiles to players |
| **[private-build.md](private-build.md)** | Build/run the private client (v171+, XIGNCODE NEO unpack, injected il2cpp, HTTP-not-TLS) |
| **[mftl-extraction.md](mftl-extraction.md)** | Recover `libil2cpp.so` from the XIGNCODE NEO container (`server/patchers/unpack_neo.py`) |
| **[emulator-note.md](emulator-note.md)** | Player-facing note (VI): why stock v171+ won't run on an emulator |
| **[multi-account-login.md](multi-account-login.md)** | Multiple accounts/devices, the web-Google login bridge (`GLOGIN_DEV=1`), transfer codes |
| **[save-editing.md](save-editing.md)** | Grant currency / items / units / skins / treasures by editing player state or sending mail |
| **[content-unlock.md](content-unlock.md)** | Unlock version-gated content (`MinVersion`) - treasures, skins, units, stages |
| **[stages-and-spawns.md](stages-and-spawns.md)** | How stage enemies are defined; build a training-dummy test stage |
| **[cdn-master-data.md](cdn-master-data.md)** | Edit master-data XML and push it to the client via the CDN xml bundle |
| **[discord-cdn-monitor.md](discord-cdn-monitor.md)** | Configure the Discord CDN-update notifier and its 30-minute monitor |
| **[api-and-crypto.md](api-and-crypto.md)** | AES request/response format; hit the server manually with curl/python |
| **[web-ui-reconstruction.md](web-ui-reconstruction.md)** | Faithfully reconstruct a client UI as a web UI using IL2CPP, AssetBundles, and client-render baselines |
| **[history/synthesis.md](history/synthesis.md)** | What nine months of transcripts contain: operating model, decisions, failure taxonomy, knowledge map |
| **[history/timeline.md](history/timeline.md)** | Project timeline, phase by phase |
| **[history/lessons.md](history/lessons.md)** | Trap ledger: every failure that cost a session |
| **[blog/index.html](blog/index.html)** | The build log, told as a story (EN/VI) |
| **[blog/full.html](blog/full.html)** | The full technical record: every step, offset and snippet (EN/VI) |
| **[next-steps.md](next-steps.md)** | What to do next to close the project cleanly - and what not to do |

## The one mental model that explains everything

There are **two separate data planes**, and knowing which one a change lands in saves hours:

1. **Server state / API responses** - `server/state/players.db` (SQLite, one row per player,
   always through `server/playerdb.py`) + the handlers in `server.py` and the route modules.
   Controls what the game *account* owns and what the REST API returns (currency, cards,
   treasures, mail). Edits here are **live per-request** (`load_state()` re-reads the row each
   call) - no restart, no client re-download.

2. **Client master data** - the CDN **xml AssetBundle** (`server/real_cdn/xml`), built from
   `server/xml_live/*.xml`. Controls what the *game client itself* reads: stage spawns, skin/unit/
   treasure definitions, localized text, `MinVersion` gates. Edits here need
   `rebuild_xml_bundle.py` → server restart → client re-download (AssetHash change).

> Granting a player a treasure = plane 1. Making that treasure *exist / be un-gated* for the client =
> plane 2. Most "I changed it but nothing happened" bugs are editing the wrong plane. See each playbook.

### Known Boundaries
- Player unit IDs are between `10000` and `10999`. Any unit ID outside this range is not a valid player unit and can crash the client if granted in a card array. `server/playerdb.py` will automatically filter these out.
- Gacha pools have been restricted to this range to prevent granting invalid testing or enemy units.
