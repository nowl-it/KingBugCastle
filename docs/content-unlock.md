# Content Unlock — version gating (`MinVersion`)

The devs ship data **ahead** of release, then gate it by version. A treasure, skin, unit, or stage can
already be fully authored (buff logic, art, localized text) yet invisible in-game because its
`<MinVersion>` is higher than the running client. Because *you* control the private server's version
gate, you can flip these on early.

## The integer version

The client's version is an **integer**, not the dotted string: v170.1.00 → **`170100`**, v171.0.00 →
`171000`. Master-data `<MinVersion>N</MinVersion>` means "released at client version ≥ N".

## Two gates to lower

1. **Server-side grant filter** — `server.py` has `> 170100` thresholds in a few places (e.g.
   `_all_treasure_ids()`, and content-gate checks around lines 169/201/226). These decide what the
   server hands out / treats as released. Grep `170100` to find them; bump when the client version bumps.

2. **Client-side master data** — the `<MinVersion>` tag inside the entry in `scratchpad/xml_live/*.xml`.
   Even if the server grants ownership, the client may hide or mis-render an entry whose local
   `MinVersion` is in the future. Lower it to the current version so the client treats it as released.

## Recipe — un-gate one entry

Example: treasure `30040` "Shadowless / Vô Ảnh" (a v171 Legacy) on a v170.1.00 client (done 2026-07-14):

```xml
<!-- scratchpad/xml_live/Treasures.xml -->
<Treasure ID="30040">
  ...
  <MinVersion>171000</MinVersion>   <!-- change to 170100 -->
</Treasure>
```

Then:
1. Lower `MinVersion` → `170100` (passes the server filter *and* the client's own gate).
2. Grant ownership if needed — treasures are auto-granted once released; others per [save-editing.md](save-editing.md).
3. Rebuild + push the bundle so the client sees it released: `rebuild_xml_bundle.py` → restart servers →
   clear cache (see [cdn-master-data.md](cdn-master-data.md)).

## Caveats

- **Only un-gate what the client can actually render.** Future content whose *art assets* aren't in the
  current client bundle (e.g. brand-new v171 Beach skins) will show broken or crash — leave those gated
  until the client updates. Un-gating is safe when the asset already ships in the current bundle (most
  data-ahead content does).
- **`ArtifactOptionUI` crash risk** for directly-granted Artifact/Treasure/Accessory — prefer the normal
  ownership path (release gate + default grant) over mail-granting them raw.
- When you **bump the whole client to a new version**, update the `170100` thresholds in `server.py`,
  `response_config.json` (`serverVersion`, `patchFolder`), and re-derive ARM64 patch offsets — see
  [../AGENTS.md](../AGENTS.md) and the version-bump discussion in the project notes.
