# Resume card — ShopPanel → gacha (cập nhật 2026-10-21)

Đọc `docs/dev-notes.md` §74–§77c trước. Trạng thái verify cuối cùng:
gate `gate_s77e` exit 0 / 0 `error CS`; capture `cap_s77` 0 NRE / `play capture ok`.

## Lệnh verify (dùng lại y nguyên)

```bash
# compile gate (PASS = exit 0 + "Exiting batchmode successfully" + 0 "error CS")
KGC_MASTER_DATA=/home/nowl/Code/kgc/server/xml_live timeout 900 \
  /home/nowl/Unity/Hub/Editor/2022.3.62f3/Editor/Unity -batchmode -nographics -quit \
  -projectPath unity/kgc-rebuild/ExportedProject \
  -executeMethod Kgc.Editor.MasterDataSmokeTest.Run -logFile /tmp/opencode/gate.log

# play capture (cần server 8080 chạy trước; PASS = 0 NullReferenceException + "play capture ok")
KGC_MASTER_DATA=/home/nowl/Code/kgc/server/xml_live KGC_CAPTURE_PLAY=1 KGC_CAPTURE_LOGIN=1 \
  KGC_CAPTURE_SETTLE=150 KGC_CAPTURE_GAMESTART=0 KGC_CAPTURE_DIR=/tmp/opencode/cap \
  timeout 900 xvfb-run -a -s "-screen 0 1280x2048x24" \
  /home/nowl/Unity/Hub/Editor/2022.3.62f3/Editor/Unity -batchmode -force-glcore \
  -projectPath unity/kgc-rebuild/ExportedProject \
  -executeMethod Kgc.Editor.CaptureScene.Run -logFile /tmp/opencode/cap.log

# disassemble arm64 theo RVA (kèm chú thích tên method)
python3 /tmp/opencode/kdis.py 0x341452C | head -120
```

## Hàng đợi port (đúng thứ tự, RVA đã kiểm chứng)

| # | Method | RVA | Ghi chú |
|---|---|---|---|
| 1 | `ShopPanel.RebuildSkinBundlePackageItems` | 0x341452C | 255 lệnh; `ForEach` → `Array.Clear` ×2 → `PackageItem.InitByPrefabType` → `SetSiblingIndex` |
| 2 | `ShopPanel.ReloadSpecialPackage` | 0x34141DC | `hasBundlePackageSkins` + `IsSkinBundlePackageItemsValid` + `Rebuild…` + pooling |
| 3 | `ShopPanel.ReloadUnitBundlePackage` | 0x3413BD4 | |
| 4 | `ShopPanel.ReloadRecommendPackage` | 0x3411394 | hàm lớn nhất file (0x2840 byte) |
| 5 | `ReloadSubscribePackage` / `ReloadPlayerPackage` / `ReloadEventPackage` | 0x3414CB4 / 0x3415220 / 0x3415AD8 | |
| 6 | `ReloadDaily` / `ReloadMoney` / `ReloadShopSubtabEnable` | 0x340C7C0 / 0x3410840 / 0x3418930 | `UpdateDaily` 0x34101C0 cần tên class của static cell `0x6950B30` |
| 7 | `ReloadPackageBadge` / `SetCashItems` / `OnClickDailyInfo` | 0x3418114 / 0x341848C / 0x3418558 | |
| 8 | `BuyGachaButtonGroup.Buy` | 0x3386C48 | viết lại theo callback (§76: `RestAPI.*` đã sẵn) |
| 9 | `HandleNewUnitGachaResult` / `HandleUnitGachaResult` / `HandleArtifactGachaResult` / `HandleTreasureGachaResult` / `HandleSkinGachaResult` | 0x33877A8 / 0x33872B0 / 0x3387640 / 0x3387E2C / 0x33881BC | lặp `ret.gachas` rồi `GachaPanel.Show` |
| 10 | `GachaPanel.Show` → `ShowResult` → animation | 0x33AD37C / 0x33AE6FC / 0x33B05F0 | animation port sau cùng; `SkipCardOpen` có thể nhảy thẳng `Hide()` |

## Bảng field/literal đã giải (dùng lại, đừng tra lại)

- `ShopPanel`: `recommendTab 0x40` · `packageTab 0x48` · `dailyTab 0x50` · `specialTab 0x58` ·
  `subscribeTab 0x60` · `moneyTab 0x78` · `unitBundlePackageToggle 0xC0` · `specialTabManager 0xD0` ·
  `packageTabManager 0x130` (index @0x20) · `packageTabsLayout 0x138` · `expRefreshTime 0x160` ·
  `unitBundlePackages 0x1E0` · `specialPackages 0x1E8` · `playerPackageItems 0x1F0` ·
  `_skinBundlePackageItems 0x1F8` · `_skinBundlePackageItemPrefabNames 0x200` · `moneyItems 0x210` ·
  `readyToReload 0x2E9` · `isReloaded 0x2EA`
- `ShopItem`: `resUnit 0xE0` · `resSkin 0xE8` (→ `ResourceBase<T>.id` @0x10)
- Literal cell: `0x69538C8 = "Special"` · `0x69817E0 = "Package"` · `0x6986300 = "PackageItemPrefab"` ·
  `0x694FC70 = ""` · `0x6986528 = "click_provability_info"` · `0x6986530 = "ProvabilityInfoURL"`

## Bẫy đã gặp (đừng lặp lại)

1. Chèn code sinh tự động phải tính index trên **chuỗi gốc** (`i1 = src.rfind('}')`, `idx = src.rfind('}', 0, i1)`); dùng `rstrip()` rồi cắt `src` → lỗi 1.725 dòng giả.
2. JSON rỗng phải là chuỗi `"{}"`.
3. Tham số optional phải bỏ `= default` khi thêm `Action<Resp> onDone` (nếu không: CS1737).
4. NRE-pad trong hàm trả `int` phải là `return default;` (`return;` → CS0126).
5. Tên method trong `script.json` là `Awesomepiece.RestAPI.<X>d__N$$MoveNext` (lọc `RestAPI.<` ra 0 dòng).
