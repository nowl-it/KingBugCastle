# Save Editing — grant currency, items, units, skins, treasures

All player-owned state lives in SQLite the server reads **per request** (`load_state()`), so edits are
live — no restart, no client re-download. This is data plane 1 (see [README](README.md)).

## Where state lives

- `server/state/players.db` — one row per player (`uid`, JSON blob). Accessed only through
  `server/playerdb.py`; WAL mode so the `:8080` and `:8443` processes and the dashboard can all
  write safely.
- `server/state/pre-sqlite-backup/` — the old `player.json` + `players/*.json`, imported once and
  **no longer read**. Editing them does nothing.
- Seed for a fresh save: `server/data/default_player.json`.

Do not edit the DB with a plain read-modify-write from another script while the server is running —
take `playerdb.write_lock()` around it, the same lock the request middleware holds.

Top-level keys: `gold cash paidCash heart level exp name cards decks inventoryItems treasures
equippedArtifacts missions tokens buildingPoints ...`.

## Easiest path — the Admin dashboard

`server/run.sh` (or `python3 server/dashboard.py`) → http://localhost:8081/. Edits `players.db`
through `playerdb`, so no restart is needed — the next `/player` fetch sees it. Tabs:

| Tab | What you can change |
|---|---|
| **Players** | create / clone / activate / delete a save; name, castle name, currencies, level, best-cleared stage & theme, building points, win counts; **raw JSON editor** for the whole save |
| **Heroes** | grant one hero or all of them; edit level, soul, potential tier; remove a hero |
| **Items** | set any inventory item's count (0 removes it), add from the full item catalog |
| **Accessories** | read-only view grouped by synergy set, with the same grade badge the client computes |
| **Mail** | send to one save or broadcast to every save, with a reward picker over the whole catalog (Item / Unit / UnitSoul / Artifact / Treasure / Accessory) |

The raw JSON editor replaces the entire save — the `uid` is pinned back to the row key on write,
everything else is taken verbatim, and there is no undo.

## Currency / level / name

Plain top-level fields inside the row's JSON blob. Set them (dashboard, or
`playerdb.load/save`) and the next `/player` or `/player/currencies` fetch reflects it:

```json
{ "gold": 99999999, "cash": 999999, "heart": 100, "level": 200, "name": "Tester" }
```

## Cards (heroes) & skins

`cards` is a **dict keyed by unitId** (string). Each card:

```json
"10000": { "unitId": 10000, "level": 30, "potentialTier": 1,
           "skins": [1000001, 1000002], "currentSkin": 1000001,
           "favoriteSkinIds": [], "randomSkinApply": false, "soul": 999 }
```

- **Own a skin** → add its id to `skins`. **Equip** → set `currentSkin`.
- Skin ids come from `Skins.xml`; a hero's skins are the `<Skin>` entries whose resolved unit = the
  hero (base has `Unit="X"`, chroma variants use `Inherit`). Only entries with a `<Prefab>` are
  renderable/ownable. Filter to `MinVersion <= 170100` to avoid future-gated skins the client can't render.
- **Unlock all skins for all heroes** — parse `Skins.xml`, group renderable released skin ids by unit,
  write each list into the matching card's `skins`. (Done 2026-07-14: 645 skins across 71 heroes.)

> **Equip persistence gotcha (fixed 2026-07-14):** `/card/equipSkin` request model is `{unit, skin}`
> (NOT `unitId/skinId`). The old handler read the wrong field names, never saved `currentSkin`, so skins
> reverted to default in lobby and never showed in battle. `set-skin-favorite` / `set-random-skin-apply`
> use `CardSkinEtcRequestModel {unitId, skinId, flag}`. See `r_card_equip_skin` in `server.py`.

## Treasures (Legacies)

`treasures` is a **list**; the server auto-grants every *released* treasure by default
(`DEFAULT_TREASURES`, built from `_all_treasure_ids()` which filters `MinVersion > 170100`). To grant a
specific one that isn't auto-included, append an entry shaped like `make_treasure()`:

```python
# item_templates["treasure"]: level 30, overcome 10 (maxed), state 0
{ "id": <next_seq_id>, "treasureId": 30040, "accountId": 1, "level": 30, "exp": 0,
  "overcome": 10, "unitId": 0, "state": 0, "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
  "createdAt": "<now>", "updatedAt": "<now>", "usedThemeList": [],
  "isEarlyAccessModeTestTreasure": false }
```

If the treasure is version-gated, the client also needs it un-gated in master data —
see [content-unlock.md](content-unlock.md). (Granting `30040` "Shadowless/Vô Ảnh" = both planes.)

## Mail rewards (safe way to grant almost anything)

`POST /post/receive` → `_grant_reward()` mutates state on claim. Supported reward types:

| Type | Effect |
|------|--------|
| Gold / Cash / Heart | currency |
| Item | `st.inventory` (id from `InventoryItems.xml`, incl. reward boxes) |
| Unit / Card | `st.cards` |
| UnitSoul | `st.cards[id].soul` |
| Artifact / Treasure / Accessory | **display-only** — gift as an Item reward box instead (direct grant can crash `ArtifactOptionUI`) |

Send via the dashboard Admin tab or by appending to a player's `posts` array (server serves it with a
`@raw:` prefix so literal title/text render, bypassing the Localizer). Mechanism: [inbox notes in AGENTS.md].
