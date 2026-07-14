# Stages & Spawns — how enemies are defined, and building a dummy stage

Stage enemy composition lives **client-side** in `Stages.xml` (inside the CDN xml bundle). The server's
`/game/start` response does **not** carry spawn data (only `code/cards/gameId/...`) — the client reads
`Stages.xml` locally. So to change what monsters appear, edit `scratchpad/xml_live/Stages.xml` and push
the bundle ([cdn-master-data.md](cdn-master-data.md)).

## Stage ID scheme

- Campaign: `theme*100 + stage`. Theme 1 (chapter **I**) = IDs `101`–`110` → "I-1" … "I-10".
- Invasion: adds a `Difficulty="N"` attribute. `<Stage ID='11001' Theme='1' Difficulty="1">` is the
  invasion diff-1 override, linked from campaign stage 110 via `<ReplacePVPStage>11001</ReplacePVPStage>`.
- `/game/start` body carries `{theme, difficulty}` (e.g. `theme:1, difficulty:1` = play theme 1 diff 1).
- **"I-1" = stage `101`** (the first stage), not `11001` (that's the I-10 boss override).

## Two spawn sources — BOTH fire

For a given stage, the client spawns the union of:

1. **Explicit** `<SpawnData Y='row'><Spawn ID=… Pos=… Level=… Boss=…/></SpawnData>` — fixed monsters at
   fixed positions (`Pos` 1–5 columns, `Y` rows/waves).
2. **Auto-fill** `<ValueSum>N</ValueSum>` — spawns **random theme-pool monsters** worth `N` total
   "value budget" (each unit has a `<Value>`; fills until spent), **on top of** the explicit ones.

Proof: stages `102`/`103`/`104` have *only* `<ValueSum>` (no explicit `<Spawn>`) yet still spawn
monsters — so `ValueSum` alone generates enemies.

> This is the trap: editing only the explicit `<Spawn>` list to dummies still leaves `ValueSum`
> auto-filling real monsters → dummies "mixed with monsters". You must zero `ValueSum` too.

## Recipe — a pure training-dummy stage

Turn a stage into harmless static dummies for fast content/damage testing (done 2026-07-14 for I-1):

```xml
<Stage ID='101' Theme='1' Inherit='1'>
  <ValueSum>0</ValueSum>                    <!-- 0 = no auto-fill of real monsters -->
  <SpawnData Y='1'>
    <Spawn ID='99999' Pos='1' Level='1'/>
    <Spawn ID='99999' Pos='2' Level='1'/>
    <Spawn ID='99999' Pos='3' Level='1'/>
    <Spawn ID='99999' Pos='4' Level='1'/>
    <Spawn ID='99999' Pos='5' Level='1'/>
  </SpawnData>
  <SpawnData Y='2'>
    <Spawn ID='99999' Pos='2' Level='1'/>
    <Spawn ID='99999' Pos='4' Level='1'/>
  </SpawnData>
</Stage>
```

Steps: (1) replace explicit `<Spawn>` monster ids with **99999**, (2) set **`<ValueSum>0</ValueSum>`**,
(3) rebuild bundle + restart + clear cache. `Inherit` on theme-1 points to empty base templates (only
`<Gold>`, no spawn), so it adds no monsters — safe to leave or drop.

### The dummy unit

`Unit ID=99999` (`허수아비` / "Training Dummy", in `Units.xml`):

| Field | Value | Meaning |
|-------|-------|---------|
| `Type` | Enemy | spawns as a target |
| `Hp` | 1000000000 | effectively unkillable |
| `Speed` | 0 | stands still |
| `Atk` / `AttackInterval` | 1 / 10000 | never attacks |
| `Pushable` | false | won't get knocked around |
| `ApplyDamageToHp` | false | HP never depletes (eternal target) |
| `Value` | 0 | contributes nothing to `ValueSum` budgets |

Unit `99997` = "moving dummy" if you want motion. Because 99999 never dies, the **stage never clears**
— it's a damage sandbox, not a beatable stage. For a *clearable* trivial stage, spawn a real monster
with low HP and neutered attack instead of 99999.
