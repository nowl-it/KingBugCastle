# CDN Master Data — edit XML, push to the client

Master data (stage spawns, unit/skin/treasure definitions, localized `Strings`, `MinVersion` gates) is
what the **client** reads. It is delivered as a Unity **AssetBundle** at `server/real_cdn/xml`, served
by the server at `/patch/<folder>/ANDROID/xml`. Editing the server's own JSON API does **not** change
this — the client reads the bundle directly. This is data plane 2 (see [README](README.md)).

## Source of truth

- **Edit** `scratchpad/xml_live/*.xml` (~143 files: `Units`, `Skills`, `Skins`, `Stages`, `Treasures`,
  every `Strings_<locale>`, …). `server.py` also reads this dir (`XML_DIR`) for its JSON API, and it is
  what `rebuild_xml_bundle.py` packs into the bundle. **Do not** edit `xml/2026_06_26/` — that's a
  pristine reference clone, not what anything reads.

## Workflow

```bash
# 1. edit scratchpad/xml_live/<File>.xml
python3 server/rebuild_xml_bundle.py     # rewrites real_cdn/xml + updates AssetHash.txt (new md5)
# 2. restart BOTH uvicorns — they cache real_cdn/ at import (see deploy-and-run.md)
# 3. clear the device's downloaded bundle cache before next launch
adb -s <serial> shell "rm -rf /sdcard/Android/data/com.nowl.castle/files/UnityCache"
adb -s <serial> shell am force-stop com.nowl.castle
```

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
