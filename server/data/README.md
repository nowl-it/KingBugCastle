# data/ — response data, edit these instead of `server.py`

See `../WORKFLOW.md` for the "which file do I edit" decision table and the restart-loop.
All four files are loaded once at `server.py` import time into module-level globals —
**restart the server after any edit here**, a running process won't pick up changes.

## `static_overrides.json`

`{ "route path": <literal response dict> }`. One entry per route whose response never
depends on `st` (player state) or `body` (request payload) — pure constants, empty lists,
fixed structs (shop, decoration, kg-wiki, roguelike stubs, clan search/ranking/raid...).

Add a new route here with no code change needed, as long as it's truly static. If the
response needs `now_iso()`, `st.get(...)`, or any per-request computation, it does NOT
belong here — see `response_config.json` or add a handler to `DYNAMIC_OVERRIDES` in
`server.py` instead.

Routes that share an identical payload under multiple paths (e.g.
`/shop`/`/shop/refreshDailyShop`, the 7 `/decoration/*` sub-actions) are NOT duplicated
here — see `_STATIC_ALIASES` near the top of `server.py`.

## `response_config.json`

Constants consumed by handlers in `server.py` that DO have per-request logic (relative
date offsets via `now_iso(n)`, `st.get()` fallback chains, gold/exp formulas). Keyed by
feature area:

| Key | Used by | Notes |
|---|---|---|
| `server` | `PATCH_FOLDER`, `SERVER_VERSION` | top-of-file server config |
| `player` | `r_player()` | `defaults` = `st.get(key, default)` fallbacks; `listDefaults` = repeated-value list fallbacks; `invasionThemeRanges`/`invasionUnlockedDifficulty` = per-theme record generation; `fixedTail`/`seasonDayOffsets`/`nextSeasonDayOffsets` = the always-constant PvP-shaped tail fields on the player response |
| `pvpInfo` | `r_pvp_info()` (served via `/pvp/matching`; `/pvp/info` itself is served by the separate direct handler using `pvpInfoDirect` below) | |
| `pvpInfoDirect` | `pvp_info_direct()` direct route handler | full static skeleton; dates are far-future fixed strings, not `now_iso()`-relative |
| `colosseum` | `r_colosseum()` | |
| `pass` | `r_pass()` | `passSeason` MUST stay a valid `SeasonPasses.xml` id (70) — see WORKFLOW.md rules |
| `gameStart` | `r_game_start()` | heart-cost-by-theme thresholds |
| `gameComplete` | `r_game_complete()` | gold/exp reward formula constants |
| `clanCreate` | `/clan/create` lambda in `DYNAMIC_OVERRIDES` | clan defaults merged with the request's name + player name |

## `item_templates.json`

Constant fields for the `make_artifact()`/`make_accessory()`/`make_treasure()`/
`make_rift_weapon()`/`make_rift_crystal()` generators in `server.py`. Per-item variable
fields (id, tier-derived option count, etc.) stay in code since they come from parsed XML
— only the constant/template parts live here.

`artifact.optCountByLevel`/`typesPool`/`maxRollLvs`/`safePositions` directly control the
`ArtifactOptionUI.Init` crash-avoidance invariant documented in `AGENTS.md` and
`documentation/GOD_ACCOUNT_DATA_AGENT_PROMPT.md` — don't change `safePositions` to more
than 1 element without re-reading that writeup first (it reproduces a client-side crash).

## `default_player.json`

The DB "seed row": `player` (identity/currency defaults), `cardTemplate` (per-hero
default level/exp/potential applied to every owned hero), `invCount` (default count for
every inventory item), `decks` (deck presets — `decks[0].deck` length defines
`DECK_SLOTS`, a crash-relevant invariant, see `AGENTS.md` "Deck-length invariant").

Only used to build `state/player.json` on first boot (or after it's deleted) — editing
this file does NOT retroactively change an existing save.
