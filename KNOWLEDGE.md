# KGC Research Project - Tài Liệu Tổng Hợp

> Game: **King God Castle** (KGC) - com.awesomepiece.castle
> Version phân tích chính: **v169.1.x** (Android ARM64)

> **Cập nhật (2026-07-14):** Client active hiện là **v170.1.00** (arm64), dump ở
> `il2cpp/v170.0.03/`. Server config `patchFolder` = `2026_07_09`. Các đường dẫn `v169.1.05`
> bên dưới là snapshot lịch sử của lần phân tích gốc. AES key `b53019bb76da6b34` vẫn dùng cho
> v170. Các hệ thống mới (accessory unlock gate theo invasion difficulty, Inbox/Post + custom
> mail `@raw:`, native il2cpp hook methodPointer-swap vs inline-detour) được ghi ở
> **`AGENTS.md`** và **`.claude/CLAUDE.md`** - không lặp lại ở đây.
>
> **Playbook vận hành** (grant item/skin/treasure, unlock content theo `MinVersion`, làm màn
> hình nộm test, edit master-data + push CDN bundle, crypto API) → **[`docs/`](docs/README.md)**.
> Two-plane model (server state vs client master-data bundle) là mấu chốt - đọc `docs/README.md`.

---

## Mục Lục

1. [Tổng quan dự án](#1-tổng-quan-dự-án)
2. [Kiến trúc game](#2-kiến-trúc-game)
3. [API Server](#3-api-server)
4. [IL2CPP Reverse Engineering](#4-il2cpp-reverse-engineering)
5. [Data Pipeline (XML / Patch CDN)](#5-data-pipeline-xml--patch-cdn)
6. [Bug Database](#6-bug-database)
7. [Công cụ (kgc CLI)](#7-công-cụ-kgc-cli)
8. [Tham chiếu nhanh](#8-tham-chiếu-nhanh)

---

## 1. Tổng Quan Dự Án

Dự án nghiên cứu / datamine King God Castle gồm:

| Mảng | Thư mục | Mục đích |
|------|---------|---------|
| API wrapper | `api/` | Gọi REST API server game |
| IL2CPP RE | `il2cpp/v<ver>/` | Reverse libil2cpp.so (dump.cs, il2cpp.h, ...) |
| Master data | `xml_history/` | Data-table XML từ CDN (Units, Skills, Strings...) |
| Unity project | `unity/` | Unity project (asset extract) - CHỈ chứa Unity project |
| Data analysis | `xml_history/`, `documentation/` | Phân tích XML game data theo version |
| Reports | `reports/` | Báo cáo patch (HTML + assets) |

**Công cụ chính:** `./kgc-cli` - CLI binary (ELF x86-64, stripped) cho asset/data operations.

**Layout rule:** `unity/` = chỉ Unity project. Master data → `xml_history/`. IL2CPP dump → `il2cpp/v<ver>/`.

---

## 2. Kiến Trúc Game

### Stack kỹ thuật

- **Engine:** Unity 2022.3.62f3
- **Scripting:** IL2CPP (C# → native ARM64)
- **Native lib:** `libil2cpp.so` (~113MB, uncompressed trong APK)
- **Anti-cheat:** Xigncode (XLSDK) - injection + speed-hack detector
- **Network:** AES-128-ECB, msgpack/JSON response
- **Asset delivery:** CDN XML patch system

### ELF libil2cpp.so

- Text segment: VA bắt đầu **0x4000**, file offset **0**
- Công thức: `file_offset = RVA - 0x4000`
- Dump tool: Il2CppDumper → `dump.cs`, `il2cpp.h`, `stringliteral.json`, `script.json`

---

## 3. API Server

### Servers

| Server | Dùng cho |
|--------|---------|
| `https://kgc-k8s-1.awesomepiece.com` | Tất cả gameplay API |
| `https://kgc-ranking-1.awesomepiece.com` | Rankings (dedicated server) |
| `https://kgc-cdn-1.awesomepiece.com/patch/LIVE/` | Patch XML CDN |
| `axis-game.awesomepiece.com` | Axis Blade collab |
| `isekai-lobbyserver.awesomepiece.com` | I Sekai collab |

### Encryption

```
Protocol:  AES-128-ECB, zero padding
Key v169+: b53019bb76da6b34  (v165-168: cnf1tl65djs2wp3g)
POST body: aes_encrypt(json) -> hex string
Response:  raw binary AES-ECB -> msgpack hoặc JSON
Header:    accesstoken: <token>   (KHÔNG phải Authorization: Bearer)
Time:      header "time": MD5(unix_timestamp)
```

### Auth flow

```
1. GET  /auth/xcdSeed          # lấy seed, không cần auth
2. [client] generate Xigncode cookie từ seed
3. GET  /auth/xcd?cookie=<c>   # validate anti-cheat, lấy accessToken
4. POST /auth/login            # với accesstoken header
5. POST /auth/shake-hand       # heartbeat mỗi ~60s
```

Xigncode cookie format: `926988XXXX_<md5_device_fingerprint>_<md5_checksum>`. accessToken không bypass được nếu không có Xigncode SDK / binary game.

### Headers chuẩn

```python
{
    "version": "169.0.03",
    "x-unity-version": "2022.3.62f3",
    "encryptedwithhex": "true",
    "Content-Type": "application/json",
    "User-Agent": "ProductName/169.0.03.0 CFNetwork/3860.300.31 Darwin/25.2.0",
}
```

### API modules (thư mục `api/`)

| Module | Endpoints chính |
|--------|----------------|
| `auth/` | login, register, transfer, xcd, shake-hand |
| `player/` | get_player_info, currencies, inventory, rename |
| `game/` | start, complete, revive, skip |
| `shop/` | get_shop, buy_shop_item, buy_iap, gacha |
| `card/` | get_all_cards, upgrade_card, buy_skin |
| `deck/` | get_deck, set_deck, set_potential |
| `clan/` | fetch, create, search, chat, raid |
| `colosseum/` | fetch, match, round data |
| `pvp/` | fetch_pvp_info, matching, rankings |
| `ranking/` | stage/pvp/colosseum/roguelike rankings, unit stats |
| `territory/` | build, upgrade, hunting, alchemy |
| `roguelike/` | load/save, startFloor, endFloor, season |
| `treasure/` | equip, exp, overcome, dismantle |
| `accessory/` | equip, change stat, preset |
| `artifact/` | craft, merge, reroll, polish, equip |
| `rift_weapon/` | upgrade, equip, reroll, crystal |
| `mission/` | missions, post box, season pass |
| `story_mode/` | save, chest reward, challenge |
| `decoration/` | advisor, map skin, login skin, flag, name tag |
| `event/` | seasonal events, babel, invasion, coupon, kg-marble |

### Quick start API

```python
from api.config import set_auth_token
from api.auth.auth import auth_with_device_id, login
from api.player.player import get_player_info

result = auth_with_device_id("your-device-uuid")
result = login(device_uuid="your-uuid", locale="vi", platform="Android")
player = get_player_info()
```

---

## 4. IL2CPP Reverse Engineering

### Files (`il2cpp/v169.1.05/`)

| File | Mô tả |
|------|-------|
| `dump.cs` | C# dump từ Il2CppDumper |
| `il2cpp.h` | C header file |
| `stringliteral.json` | String literals |
| `script.json` | Method scripts |
| `DummyDll/` | Dummy assemblies cho Ghidra/IDA import |

### Dump.cs format

```
// Namespace.ClassName
// RVA: 0x31C7604  Offset: 0x31C3604  VA: 0x31C7604
void MoveNext() { }
```

- **RVA** = virtual address tương đối (= VA nếu base=0)
- **Offset** = file offset trong libil2cpp.so = RVA - 0x4000

Dùng để tra signature/RVA hàm khi đối chiếu Ghidra với mã nguồn datamine.

---

## 5. Data Pipeline (XML / Patch CDN)

### CDN layout

```
kgc-cdn-1.awesomepiece.com/patch/LIVE/
  <date>/
    ANDROID/xml/ExportedProject/Assets/patchresources/datas/
    IOS/xml/ExportedProject/Assets/patchresources/datas/
```

### Dữ liệu local

- `xml_history/<date>/` - snapshot XML theo version (2025_11_18 ... 2026_06_26).

So sánh version: dùng `./kgc-cli compare <v1> <v2>` (thay cho script Python thủ công cũ).

### XML files quan trọng

| File | Nội dung |
|------|---------|
| `Units.xml` | Thông số hero (34k dòng) |
| `Skills.xml` | Kỹ năng (44k dòng) |
| `Skins.xml` | Skin data (35k dòng) |
| `Stages.xml` | Stage configuration (18k dòng) |
| `BabelStages.xml` | Babel Tower (99k dòng) |
| `Strings_*.xml` | Localization x13 ngôn ngữ |
| `ColosseumSettings.xml` | Cài đặt Colosseum |
| `Missions.xml` | Mission data (31k dòng) |
| `Artifacts.xml` | Bảo cụ (artifact) |
| `TreasureBuffDatas.xml` | Cổ vật buff data (14k dòng) |
| `ClanRaid*.xml` | Clan raid (settings, boss power, rank tiers) |

### documentation/scripts/

Subproject RAG/Obsidian pipeline (git repo riêng):

| Script | Mục đích |
|--------|---------|
| `kgc_pipeline.py` | Main pipeline orchestrator |
| `parse_game_data.py` | Parse XML -> JSON |
| `generate_hero_profiles.py` | Hero profile docs |
| `generate_version_changelog.py` | Changelog tự động |
| `build_training_corpus.py` | JSONL corpus cho LLM |
| `diff_game_data_exports.py` | Diff giữa versions |
| `validate_tier_scaling.py` | Check tier scaling |
| `obsidian_semantic_search.py` | Semantic search trong docs |
| `ollama_autodoc.py` / `rag_service.py` | AI doc generation (local Ollama) |
| `simulate_stats.py` | Simulate hero stats |

---

## 6. Bug Database

Bugs phát hiện từ phân tích XML data (báo cáo dạng quan sát, không kèm dump datamine).

### v169.0.03 - 10 bugs (2026-05-27)

| ID | Severity | Mô tả |
|----|----------|-------|
| BUG-1 | HIGH | 5/6 Slime Chapter stones: mô tả cũ ở 12/13 ngôn ngữ |
| BUG-2 | HIGH | Arabic (AR) thiếu 27 string keys so với KR |
| BUG-3 | MEDIUM | 11 string KR mới chưa dịch ở 12 ngôn ngữ non-KR |
| BUG-4 | LOW | `IceTime_14000="1.5"` fail int.TryParse -> freeze guard bị skip |
| BUG-5 | LOW | `ShopItemName_6548`: "IIV" Roman numeral sai (phải là "VII"/"VIII") |
| BUG-6 | LOW | Necromancer (12030): TODO đổi AfterCastSkill -> CastSkill chưa resolve |
| BUG-7 | LOW | Colosseum setting chưa migrate sang season system |
| BUG-8 | LOW | `DamagePer` stat type rename chờ implementation |
| BUG-9 | LOW | 2 missions đánh dấu xóa Sept 2025 vẫn còn |
| BUG-10 | LOW | 3 orphan string keys trong non-KR nhưng không có trong KR |

---

## 7. Công Cụ (kgc-cli)

Dùng để tự động hoá các tác vụ xử lý data/tài nguyên lặp đi lặp lại.

```bash
./kgc-cli <COMMAND>
```

| Command | Mục đích |
|---------|---------|
| `download` | Download XAPK từ APKPure |
| `c2u` | Convert XAPK -> Unity project |
| `compare` | So sánh 2 Unity project version |
| `proxy` | MITM proxy capture API traffic |
| `unity` | Unity asset parsing (parse-prefab, list-heroes, export-hero) |
| `config` | XML config management |
| `deps` | Dependency management (tools) |
| `il2cpp` | IL2CPP metadata dumping |
| `tui` | Interactive TUI mode |

Binary: `/home/nowl/Code/kgc/kgc-cli` (ELF x86-64, stripped).
**Luôn dùng `./kgc-cli` trước - không chạy Python script thủ công nếu CLI làm được.**

---

## 8. Tham Chiếu Nhanh

### Colosseum / Arena IDs

| Tên | ID |
|-----|----|
| Strife Battlefield | Colosseum theme 3000 |
| ChungAh hero | 10260 |

### Game IDs quan trọng (từ XML)

| Loại | ID | Ghi chú |
|------|----|---------|
| King Slime stone | 14000 | `IceTime="1.5"` bị bug |
| Lily hero | 10150 | Reworked skills v169 |
| Saeryung / Thế Linh | 10560 | Crimson Shaman, bảo cụ 30038 |
| Hwahonga / Hoa Hồn Ca | 30038 | Cổ vật - đổi tên "Khúc Ca Lửa và Linh Hồn" |
| Neria | 10780 | Hero 2026-06-02 |
| Purity / Thuần Khiết | 30037 | Bảo cụ chưa ra mắt, hero Lily |
| Ophelia / Cassie | 10790 / 10800-10810 | Dimension hero patch 2026-06-16 |
| Cathy (base) | 10800 | Dimension Shadow, transform unit → 10810 |
| Cathy (berserk) | 10810 | SubName redirect → UnitSubName_10800 |
| Clan Raid boss | 42200 / 42500 | Sứ Đồ Máu (mùa sau) / Sứ Đồ Tham Vọng (mùa này) |

### Dimension Hero Skill Data Pattern

Skill tiers (Tier 1-4) dùng `Inherit` chain từ skill base:
```
Skill<N> (Tier <N>)
  → TransformSkill<1080N>
    → BuffAtCastSkill<10800N>
      → BaseDef/BaseMDef (scale per tier)
```

| Tier | Skill ID | Transform | Buff | BaseDef | BaseMDef |
|------|----------|-----------|------|---------|----------|
| 1 | 10800 | 10805 | 108000 | 200 | 200 |
| 2 | 10801 | 10806 | 108001 | 300 | 300 |
| 3 | 10802 | 10807 | 108002 | 400 | 400 |
| 4 | 10803 | 10808 | 108003 | 500 | 500 |

Per-tier `<Name>`/`<Desc>` override có thể set trực tiếp trong skill definition (không cần redirect). Keys được định nghĩa trong `scratchpad/xml_live/Strings_*.xml`.

### Known Bugs (giải pháp tạm thời)

| Bug | Fix | File |
|-----|-----|------|
| Skill 10808 Inherit="108200" (không tồn tại) | Sửa thành Inherit="10805" | `scratchpad/xml_live/Skills.xml` |
| Unit 10810 thiếu SubName | Redirect → `UnitSubName_10800` | `Units.xml` |

### Files cần tra khi debug

| Vấn đề | File |
|--------|------|
| API endpoint | `api/<module>/<module>.md` |
| RVA hàm | `il2cpp/v169.1.05/dump.cs` |
| Skin / Unit / String | `xml_history/<date>/.../*.xml` |
| Skill data | `scratchpad/xml_live/Skills.xml` |
| String keys (live) | `scratchpad/xml_live/Strings_*.xml` |

---

*Tổng hợp từ: source code, IL2CPP RE, XML data parsing. Cập nhật: 2026-07-14.*
*Playbook thao tác (save-edit, unlock, stage/dummy, CDN, crypto): [`docs/`](docs/README.md).*
