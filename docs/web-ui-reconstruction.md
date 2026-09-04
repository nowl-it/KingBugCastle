# Reconstructing a Game UI as a Web UI

This playbook is for creating a faithful web representation of a King God Castle
screen. Do **not** start by designing an approximation in CSS. The client has the
authoritative visual hierarchy, state model, sprite atlas, and final rendered
layout; use all four.

## Two useful deliverables

1. **Visual baseline** - an exact, static client render with semantic web hotspots.
   It is the correct first milestone for pixel comparison and controller discovery.
   It does not yet make the UI data-driven.
2. **Independent web implementation** - recreated DOM/canvas controls using exported
   game assets and client-derived state/behavior. Build this only after the baseline
   has been accepted.

Do not present a baseline as a complete port. Its job is to prevent visual drift
while the independent implementation is built and compared.

## Required inputs

For one screen, collect all of the following from the **same game version**:

- decrypted `libil2cpp.so` and `global-metadata.dat`;
- the AssetBundle files from the matching APK;
- a screenshot of the actual target screen and state from the emulator;
- the relevant master-data row (unit, skin, item, etc.).

Mixing versions causes wrong method RVAs, different serialized fields, and sprites
that no longer match the live client.

## 1. Identify the controller before writing UI

Dump the matching client with Il2CppDumper. The output is intentionally temporary;
write it under `/tmp`, not the repository.

```sh
mkdir -p /tmp/kgc-ui/dump
unzip -p apk/xapk_extracted_v17201/base_assets.apk \
  assets/bin/Data/Managed/Metadata/global-metadata.dat \
  > /tmp/kgc-ui/global-metadata.dat

dotnet /tmp/kgc-ui/tools/Il2CppDumper/Il2CppDumper.dll \
  il2cpp/v172.0.01/libil2cpp_v17201_ssl.so \
  /tmp/kgc-ui/global-metadata.dat /tmp/kgc-ui/dump
```

Search `dump.cs` for the concrete panel and read its fields and public click methods.
Do not infer UI semantics from a screenshot alone.

### Verified example: v172.0.01 Hero Detail

The owned-hero detail screen is `CardInfoPanel`, not `UnitInfoPanel` (the latter is
the in-battle popup).

| Client detail | Evidence |
|---|---|
| Primary panel | `CardInfoPanel`, `Show` RVA `0x31829FC` |
| Tabs | Hero `0`, Growth `1`, Profile `2`, Skin `3` |
| Hero fields | title/name/subname/level, `UnitIllust`, role/region, 6 stats, skills, EXP/soul, potential, treasure/accessories |
| Relevant actions | `OnClickToggleDotIllust`, `OnClickUnitStatistics`, `OnClickSkillButton`, `OnClickTab(int)` |

Record this mapping beside the web implementation so a later agent knows which
client method owns each interaction.

## 2. Export original assets, not CSS lookalikes

Use `UnityPy` to enumerate and export individual `Sprite` objects. Relevant sprite
names frequently live in files such as:

- `spriteatlases_assets_atlas_ui_general_*.bundle` - `Frame_Big_Gray`, `Tab_00`,
  `Tab_Disabled_00`;
- `spriteatlases_assets_atlas_unitrelateduis_*.bundle` - `Item_Frame_00`,
  `Main_Frame_00`;
- `spriteatlases_assets_atlas_ui_icons_*.bundle` - `ActiveSkill_Frame_02`;
- `spriteatlases_assets_atlas_treasureicon_*.bundle` -
  `Treasure_Frame_Hexa_Empty`;
- `illusts_assets_all_*.bundle` - large hero illustrations such as
  `Unit_Illust_10570`.

Minimal one-off exporter:

```python
import UnityPy

env = UnityPy.load("path/to/bundle")
for obj in env.objects:
    if obj.type.name == "Sprite" and obj.read().m_Name == "Frame_Big_Gray":
        obj.read().image.save("assets/ui/Frame_Big_Gray.png")
```

Keep the source sprite name in the output filename. For a reusable export pipeline,
record the APK version and source bundle in a manifest. Never replace a game frame,
tab, slot, or glyph with a hand-drawn CSS imitation when the source sprite exists.

## 3. Capture the client render as a fidelity baseline

Navigate the emulator to the exact target state, then capture a lossless PNG. This
is a visual test fixture, not a substitute for the eventual data-driven UI.

```sh
adb -s localhost:5555 exec-out screencap -p > /tmp/kgc-ui/hero-detail.png
```

Copy the accepted fixture into the prototype's `assets/` directory and render it
at its native aspect ratio. Add transparent, keyboard-accessible buttons over
controls only after mapping each to the controller action discovered in step 1.
This gives a reviewable screen that is pixel-identical to the client while behavior
is being ported incrementally.

## 4. Build independently, one source-owned behavior at a time

After the baseline is accepted:

1. replace one baseline region with DOM/canvas using exported sprites;
2. bind it to the equivalent server/master-data state;
3. port the corresponding controller behavior from the dump;
4. compare it against the fixture at the same viewport; and
5. repeat, leaving untouched baseline regions in place until their replacement
   matches.

For Hero Detail, the order is: Hero tab → Pixel/illustration toggle → skill tooltip
→ equipment and treasure → Growth → Profile → Skin → Statistics popup.

## Verification checklist

- The baseline screenshot and web page use the same native aspect ratio.
- Every visible non-text frame, icon, illustration and slot comes from a named client
  sprite or the baseline fixture.
- Every hotspot has an accessible label and a mapped client method.
- `node --check app.js` and `git diff --check` pass.
- Do not overwrite unrelated dashboard assets or modify the live dashboard while
  prototyping; use a dedicated folder first.

## Current reference

`server/hero-detail-prototype/` is the v172.0.01 Farael Hero-tab baseline. It
contains the source client render, `Unit_Illust_10570`, selected exported UI sprites,
and the mapping to `CardInfoPanel` handlers.
