# KGC API Quirks & Known Issues

This document tracks known API quirks, design mismatches, and specific implementation details for the KGC private server.

## 1. Gacha Keys and Shop Items (`KeyItem`)
- **Issue**: The Gacha keys logic can wrongly deduct keys instead of diamonds if the `KeyItem` is read from `Gachas.xml`. `Gachas.xml` often uses the Banner ID (e.g., 302) as the `<KeyItem>`, which is not a real inventory item.
- **Fix/Rule**: Always read the `<KeyItem>` from `ShopItems.xml`. `ShopItems.xml` defines the actual inventory item ID for the Gacha tickets (e.g., 312 for King God Gacha). See `shop_routes.py` `_shop_buy`.

## 2. Gacha Results (`TreasureGacha`, `ArtifactGacha`)
- **Issue**: Standard `Results/Result` nodes for `TreasureGacha` and `ArtifactGacha` in `Gachas.xml` do not define what items drop. If the server naively uses these nodes, it assigns random hero IDs (`unitId`) to the `TreasureGacha` type, crashing the client UI or rendering fallback scroll icons.
- **Fix/Rule**: 
  - For `TreasureGacha`, the server MUST parse the `<FixedTreasures>` node, select a Treasure based on `<Treasure Rarity="...">`, and map it to `type: "Treasure"` with a valid `unitId` from `Treasures.xml`.
  - For `ArtifactGacha`, parse `<FixedArtifacts>`. It can specify `ID`, or `FromType`/`Level` pairs. The server must map this to `type: "Artifact"` and return a valid Artifact ID.

## 3. Empty API Endpoints
- **Issue**: Several endpoints (like `r_iap_restore_add`) return an empty `{}` or partial model.
- **Rule**: KGC tolerates empty `{}` responses for many endpoints (especially Colosseum or IAP ack routes). However, if an endpoint is expected to mutate client state (e.g., unlocking items, gacha rolls), returning an empty model causes desync.

## 4. Artifact Rewards (`ArtifactOptionUI` crash)
- **Issue**: The private server previously had a bug where direct Artifact granting crashed the client's `ArtifactOptionUI` due to `targets.Count` mismatches.
- **Fix/Rule**: `make_artifact` in `server.py` now strictly ensures `targets.Count == opt_count` (e.g., 1 for Normal, 4 for KingGod). Artifacts can now safely be granted directly via `_grant_reward(..., "Artifact", ...)`.

## 5. Gacha Banner Resolution & Duplication Rules (`GachaShopPanel`)
- **Issue**: `GachaShopPanel.Reload` in the Unity client populates child banners for parent gachas (e.g., Hero Summon ID `100`, Legacy Summon ID `102`, Skin Summon ID `103`) via two separate passes:
  1. `ShopResponseModel.availableTimeLimitGachas` returned by the `/shop` endpoint.
  2. The `<Gacha ID="..." Children="...">` attribute defined in `Gachas.xml`.
  If a child Gacha ID is listed in **both** `availableTimeLimitGachas` **and** `Children="..."`, `GachaShopPanel` adds it twice to `_childGachas` without deduplication. This causes duplicate banner cells, distorted page indicator counts (dots), and navigation glitches.
- **Fix/Rule**:
  - `availableTimeLimitGachas` in `shop_routes.py` must ONLY list active time-limited pickup gachas that are **not** already listed in a parent's `Children="..."` attribute.
  - Permanent base gachas (e.g., Hero Normal ID `300`, Legacy Normal ID `3999`, Skin Gacha ID `7000`) belong in `Children="..."` of their parent in `Gachas.xml`.
  - Active pickup gachas (e.g., Hero Pickup ID `1043`, Custom Unit Pickup ID `2007`, Legacy Pickup ID `5052`, Dimension Gacha ID `8001`) belong in `availableTimeLimitGachas`.
  - Expired pickup gachas must be kept with `Parent=None` or excluded from `availableTimeLimitGachas` so the client does not mark them expired mid-load.

