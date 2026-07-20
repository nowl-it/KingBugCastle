# KGC Private Server — Operator Knowledge Base

Practical playbooks for **running and modifying** the King God Castle private server:
how to grant items, unlock content, build test stages, edit master data, and deploy
changes to a client. This is the *how-to-operate* layer.

It complements the other docs — read those for the *why* and the *internals*:

| Doc | Scope |
|-----|-------|
| **[../README.md](../README.md)** | Project landing, feature list, repo layout |
| **[../SETUP.md](../SETUP.md)** | First-run: clone → `setup.py` → run your own server |
| **[../SHARE.md](../SHARE.md)** | Distribute a baked XAPK to remote players |
| **[../AGENTS.md](../AGENTS.md)** | ARM64 binary-patch inventory, RVA map, il2cpp internals |
| **[../KNOWLEDGE.md](../KNOWLEDGE.md)** | Datamine reference: API modules, IL2CPP, master-data files |
| **[../server/WORKFLOW.md](../server/WORKFLOW.md)** | Day-to-day edit/test/deploy loop, "which file do I edit" |

## This folder

| Playbook | Use it to |
|----------|-----------|
| **[deploy-and-run.md](deploy-and-run.md)** | Start the two servers, connect a device, push a change to the client |
| **[v171-private-build.md](v171-private-build.md)** | Build/run the **v171** client (XIGNCODE NEO unpack, injected il2cpp, HTTP-not-TLS) |
| **[mftl-extraction.md](mftl-extraction.md)** | Recover `libil2cpp.so` from the v171 XIGNCODE NEO container |
| **[v171-emulator-note.md](v171-emulator-note.md)** | Player-facing note (VI): why stock v171 won't run on an emulator |
| **[save-editing.md](save-editing.md)** | Grant currency / items / units / skins / treasures by editing player state or sending mail |
| **[content-unlock.md](content-unlock.md)** | Unlock version-gated content (`MinVersion`) — treasures, skins, units, stages |
| **[stages-and-spawns.md](stages-and-spawns.md)** | How stage enemies are defined; build a training-dummy test stage |
| **[cdn-master-data.md](cdn-master-data.md)** | Edit master-data XML and push it to the client via the CDN xml bundle |
| **[api-and-crypto.md](api-and-crypto.md)** | AES request/response format; hit the server manually with curl/python |

## The one mental model that explains everything

There are **two separate data planes**, and knowing which one a change lands in saves hours:

1. **Server state / API responses** — `server/state/*.json` + `server.py` handlers. Controls what the
   game *account* owns and what the REST API returns (currency, cards, treasures, mail). Edits here are
   **live per-request** (`load_state()` re-reads the file each call) — no restart, no client re-download.

2. **Client master data** — the CDN **xml AssetBundle** (`server/real_cdn/xml`), built from
   `server/xml_live/*.xml`. Controls what the *game client itself* reads: stage spawns, skin/unit/
   treasure definitions, localized text, `MinVersion` gates. Edits here need
   `rebuild_xml_bundle.py` → server restart → client re-download (AssetHash change).

> Granting a player a treasure = plane 1. Making that treasure *exist / be un-gated* for the client =
> plane 2. Most "I changed it but nothing happened" bugs are editing the wrong plane. See each playbook.
