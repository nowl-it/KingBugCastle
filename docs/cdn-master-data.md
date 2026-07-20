# CDN Master Data — edit XML, push to the client

Master data (stage spawns, unit/skin/treasure definitions, localized `Strings`, `MinVersion` gates) is
what the **client** reads. It is delivered as a Unity **AssetBundle** at `server/real_cdn/xml`, served
by the server at `/patch/<folder>/ANDROID/xml`. Editing the server's own JSON API does **not** change
this — the client reads the bundle directly. This is data plane 2 (see [README](README.md)).

## Source of truth

- **Edit** `server/xml_live/*.xml` (~143 files: `Units`, `Skills`, `Skins`, `Stages`, `Treasures`,
  every `Strings_<locale>`, …). `server.py` reads this dir (`XML_DIR`) for its JSON API, and it is
  what `rebuild_xml_bundle.py` packs into the bundle. The fallback `xml/<patchFolder>/` is a
  pristine reference clone from the CDN fetch — never edit it.

## Our edits live in code, not in xml_live

Every change we make on top of the devs' pristine data is a function in the
**`server/local_mods/`** package — one idempotent `apply(xml_dir)`, the single source
of truth. A data refresh overwrites `xml_live` wholesale and then replays these, so we
never hand-merge 143 files. The 5 mods (all real fixes, no fabricated numbers):

1. `CCRatio -100 → 0` — enemies become crowd-control-able
2. Treasure 30040 (Shadowless) gate → `170100` — shows on a fallback v170 client
3. Stage 101 dummy spawns — chapter I-1 walk-over clearable for testing
4. `UnitPanelData` 10800/10810 — Cathy/Alessia Profile tab (devs shipped no entry)
5. Cathy Overcome field typo — `{Overcome:...AuraDamagePer}` → `...AuraTotalDamagePer`
   (the value 10/20 is real in Units.xml; only the string's field name was wrong)

`apply()` is idempotent and appends a **WARN** when an anchor is gone (the devs
restructured a block we patch) — that is the one thing a human must resolve.
`python3 server/local_mods/__init__.py --check` self-tests all five.

## Workflow — two refresh paths, both replay local_mods

```bash
# NEW PATCH (devs cut a new CDN folder): fetch, normalize changed files, replay mods,
# rebuild bundle, bump patchFolder:
python3 server/refresh_master_data.py            # --dry-run / --no-bump available

# REPUBLISH (devs rewrote the SAME folder in place — folder name unchanged, so the
# diff above sees nothing; check_cdn_update.sh flags it via the bundle etag):
kgc-cli config fetch -o /tmp/kgc_xml
kgc-cli config extract -o xml_history/<date> /tmp/kgc_xml/xml_bundle_*
python3 server/rebase_xml_live.py xml_history/<date>   # wipe xml_live from pristine + replay mods

# Then, for either path:
python3 server/rebuild_xml_bundle.py             # real_cdn/xml + AssetHash
# Restart BOTH uvicorns — they cache real_cdn/ at import (see deploy-and-run.md).
# The client re-downloads when AssetHash's md5 changes; clearing cache is belt-and-braces:
adb -s <serial> shell "rm -rf /sdcard/Android/data/com.nowl.castle/files/UnityCache/Shared/xml"
adb -s <serial> shell am force-stop com.nowl.castle
```

Both paths keep `xml_live` uniformly LF (the CDN ships CRLF). Version gates +
`serverVersion` are deliberately NOT bumped — they track the deployed client APK, not
the newest game version.

The `xml` line in `AssetHash.txt` (format `<name>:<md5hex>_<sizeInt>`) changes on every rebuild. The
client's CDN check compares hashes and **re-downloads** the bundle when it differs — so the hash change
is what actually pushes your edit. Confirm the client re-fetched by watching the TLS log for
`CDN GET /patch/<folder>/ANDROID/xml -> HIT`.

## Verify the bundle actually contains your edit

```python
import UnityPy
env = UnityPy.load("server/real_cdn/xml")
for o in env.objects:
    if o.type.name == "TextAsset":
        d = o.read()
        if getattr(d, "m_Name", "") == "Stages":            # or Skins / Treasures / Strings_VI ...
            s = bytes(d.m_Script).decode("utf-8", "ignore") if not isinstance(d.m_Script, str) else d.m_Script
            print(s[s.find("ID='101'"): s.find("ID='101'") + 300])
```

## CRITICAL gotcha — no comments in Strings files

`Strings_VI.xml` / `Strings_EN_US.xml` (and other locales) must contain **zero XML comments**
(`<!-- -->`). The client's `Localizer.ParseTextAsset` mishandles comment nodes while iterating
`<String>` children — a single comment silently breaks the **entire locale's** runtime dictionary, so
every `Localize(key)` returns the raw key. This is not size-related. `rebuild_xml_bundle.py` refuses to
run if it finds a comment in a Strings file — do not bypass that check. (`Skills`/`Units`/`Stages` use a
more tolerant parser; comments there are fine.)

## Key-redirect trick (localize content the devs never localized)

`Skill`/`ActiveSkill` entries accept explicit `<Name>`/`<Desc>`/`<LongDesc>`/`<ShortDesc>` tags (and
`Unit` accepts `<SubName>`) that redirect the Localizer lookup to **any existing key**. Without the tag,
the game derives the key from the entry's own id (`"SkillName_" + id`). Use this to borrow already-
translated text, or add fresh keys to `Strings_*` for content that shipped with only dev annotations.

## Reverting

Pristine `xml` bundle backup: `server/real_cdn/xml.bak` (restore from here, don't re-clone). The
`real_cdn/` clone is folder-agnostic — served by filename — so bumping `patchFolder` in
`response_config.json` needs no re-clone.
