# Knowledge synthesis — what nine months of transcripts actually contain

This is the distilled output of harvesting **every** conversation about this project from
five agent tools. It is not a timeline (`timeline.md`) and not a failure list
(`lessons.md`); it is the answer to *"if all those transcripts disappeared, what would
actually be lost?"*

## What was harvested

| Source | Store | Sessions | Turn records |
|---|---|---|---|
| OpenCode | `~/.local/share/opencode/opencode.db` (two schemas: `message`+`part`, `session_message`) | 215 | 43,602 |
| Codex | `~/.codex/state_5.sqlite` (`threads`; rollout JSONL already deleted) | 31 | 31 |
| Claude Code | `~/.claude/history.jsonl` | 22 | 1,282 |
| Qoder | `~/.qoder/projects/-home-nowl-Code-kgc/*.jsonl` | 14 | 14 |
| Antigravity | `~/.config/Antigravity/User/globalStorage/state.vscdb` (protobuf — titles only) | 1 | 11 |
| **Total** | | **283** | **44,940** |

Reproduce with `scripts/history/extract_chats.py` (writes to `.tmp/corpus/`, gitignored) and
`scripts/history/build_history.py` (writes `sessions.md` + `stats.json`).

Codex dominates input volume (287 M tokens across 31 threads) because a single thread there
is one long autonomous run; OpenCode dominates turn count because it is one prompt per turn.
Claude and Qoder stores carry no token usage at all — a gap in those tools' history formats,
not in the project.

---

## 1. How the project was actually run

The working model never changed:

1. **The user brings intent and judgement, not code.** Instructions are short and outcome-shaped
   ("cấp cho tôi 1 cái rift crystal để test", "game báo failed to connect server"). Almost no
   prompt describes an implementation.
2. **The agent is expected to find the truth itself** — decompile, dump, diff, read the master
   data — and to say when it cannot.
3. **The user verifies on a real device, every single time.** Screenshots come back as evidence.
   Nothing is "done" because the agent says so; it is done when the panel renders.
4. **Context lives in the repository, not in the conversation.** `AGENTS.md`, `dev-notes.md`,
   `HANDOVER.md` are re-read at the start of nearly every session. That is why they are written
   as lookups, not prose.

The failure mode this model punishes hardest is **plausible invention**. 12% of all user
prompts contain an explicit bug report and 22% contain an iteration marker ("lại", "vẫn",
"nữa") — the single most repeated sentence in the corpus is
*"Continue if you have next steps, or stop and ask for clarification if you are unsure how to
proceed"* (44 times), which is the harness's own prompt, but the pattern is unmistakable: the
user spent a large share of the project re-verifying claims rather than receiving new work.

## 2. What the work consisted of

Ranked by how often the user had to ask for it (keyword share of 1,165 user prompts):

| Rank | Theme | What it looked like |
|---|---|---|
| 1 | UI / panel behaviour | "vẫn hiển thị sai", crash on a specific panel, a stat that does not update until restart |
| 2 | Master data / XML | adding a row, diffing a republish, text keys, `MinVersion` gates |
| 3 | Client build | patch, sign, rename, install on redroid, "did you actually change the host?" |
| 4 | Player state / grants | give item, reset hero, fix an account, repair a save |
| 5 | Assets | skin pipeline, sprite atlas, VFX, illustration extraction |
| 6 | il2cpp / offsets | dump, decompile, find the function, re-derive on a version bump |
| 7 | Dashboard / portal | admin UI, player portal, i18n |
| 8 | Shop / gacha | purchase paths, duplicate heroes, key items, pity |
| 9 | Deploy / hosting | CDN, TLS, Cloudflare, service units, CI |
| 10 | Docs / cleanup | commit, push, reorganise, write it down |

The ordering is the interesting part: **the project was never primarily about the server.**
Server-side emulation was solved early and stayed solved. Nearly all residual work was the
client's refusal to accept correct data in the wrong shape.

## 3. Decisions that still govern the codebase

Each of these was argued about at least once and should not be reopened casually.

| Decision | Why it exists | Anchor |
|---|---|---|
| Answer **every** route; a missing model is a bug, not a fallback | an empty response model crashes panels (ranking, shop, deck) | `docs/README.md` → two data planes |
| `RewardResponseData.type` is a closed vocabulary, translated at the wire boundary | one function (`_wire_rewards`) keeps state keys stable while satisfying the client | `AGENTS.md` → inbox |
| Derive time boundaries; never persist them | a stored `tomorrow` caused a 1 Hz re-login loop | `server/tests/test_daily_reset.py` |
| Never guess an identity; id-less login is refused in multiplayer | the fallback handed out other players' saves | `deploy` of de175b6 |
| One key per fact (altar points, accessory sub-stats) | duplicated keys diverged silently | `test_building.py`, `test_accessory.py` |
| Never hand-patch the shipped `.so`; regenerate from pristine | 21 stray bytes caused an "inherent framework bug" | `make_v171_ssl_so.py --check` |
| The `ldr → mov` klass patches stay off | the theory was disproven by a diagnostic NRE trap | `AGENTS.md` §black lobby |
| Free tier only | user mandate, not a preference — it shaped CDN, storage and CI | `docs/public-hosting.md` |
| Client lib and metadata must come from the same build | string-literal indices are compiled in; mismatch = gibberish | `docs/mftl-extraction.md` |
| Version offsets are per-build tables, never a delta | the NEO loader itself changed shape between versions | `server/builders/build_private.py` |

## 4. Failure taxonomy — how this project actually lost time

Four kinds, in descending cost:

**a) Symptom patching.** A patch applied above an unread function. Every one of the multi-session
rabbit holes (black lobby, corrupt `.so`, `UseAssetBundle` recursion) is this. The recoverable
signal is that the fix "works" but a neighbouring panel breaks.

**b) Two representations of one fact.** Storage plus derived value, protocol key plus admin key,
two gacha buy paths, two sub-stat sources. These never fail loudly; they drift, then one path
is silently wrong for weeks.

**c) Trusting the tool.** The hook reports "installed"; the loader grabs the wrong `dlopen`
handle; `r-xp` never matches under a translator; a dumped file was patched by hand. Each of these
looks like success.

**d) Silent platform divergence.** Analytics inside an HTTP client on a device without Play
Services; CMS/CF headers trusted on a loopback proxy; a proxy config that changed while its test
did not. The code was correct for an environment that no longer existed.

Notably absent from the list: algorithmic difficulty. Nothing here is hard computer science.
The difficulty is entirely *epistemic* — knowing which layer is lying.

## 5. Where each answer now lives

| If you need… | Read |
|---|---|
| a specific binary offset / RVA | `AGENTS.md` (patch inventory, per version) |
| a decode with its verification method | `docs/dev-notes.md` |
| an operator task (grant, unlock, stage) | `docs/README.md` |
| the two data planes mental model | `docs/README.md` |
| how a subsystem was reverse-engineered | `docs/api-quirks.md`, `docs/stages-and-spawns.md`, `docs/web-ui-reconstruction.md` |
| why a design is the way it is | `docs/history/synthesis.md` §3 (this file) |
| what already broke | `docs/history/lessons.md` |
| when something happened | `docs/history/timeline.md` |
| what was tried and abandoned | `docs/history/sessions.md` (titles are descriptive) |
| what to do next, and what not to | `docs/next-steps.md` |

## 6. What transfers outside this game

Five things stayed true across every subsystem, and are the only parts worth carrying to
another project:

1. **Read the consumer, not the producer.** The spec was never the server's opinion; it was the
   compiled client. Any reverse-engineering effort should allocate its first week to the
   consumer.
2. **Invariants outrank features.** Every fixed-size array, closed vocabulary and required field
   cost more than any feature that was added. Write them down as tests the moment you learn one.
3. **Prefer provable absence to plausible presence.** "I have not decompiled this yet" is a
   cheaper sentence than a wrong root cause — by an order of magnitude, measured in sessions.
4. **Derive, don't store.** Time boundaries, hashes, gates, offsets: anything copied into state
   is a scheduled bug with an unknown date.
5. **One writer, one key.** Every duplicated representation in this project eventually produced
   a support ticket that read like a data-loss report.

## 7. Ten lines for whoever picks this up

1. Read `docs/dev-notes.md` **before** touching a task; it is the decoded past.
2. Start the server with `python3 -m uvicorn server.server:app` (namespace package).
3. Two servers: HTTP `:8080`, TLS `:8443`; device needs both `adb reverse` rules.
4. `il2cpp` (the dumper) blocks on "press any key" — feed stdin or you will hang.
5. Resolve crash frames through `script.json`; file offset = RVA − 0x4000 **for libil2cpp only**.
6. Never edit `libil2cpp*_ssl.so` by hand; regenerate and run `--check`.
7. Master-data edits need `rebuild_xml_bundle.py` + restart + client re-download.
8. Save edits go through `playerdb.py`; there is no `save_player` (it is `save(uid, st)`).
9. Verify on a device. The agent will tell you it works; the panel will disagree.
10. If you cannot prove it, say so. That is the whole method.
