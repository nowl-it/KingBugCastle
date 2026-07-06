# KGC API Reference

**Base URL:** `https://kgc-k8s-1.awesomepiece.com`  
**Ranking Server:** `https://kgc-ranking-1.awesomepiece.com`  
**Patch CDN:** `https://kgc-cdn-1.awesomepiece.com/patch/LIVE/`

Source: il2cpp reverse engineering v169.0.03 + stringliteral.json

---

## Cấu trúc folder

```
api/
├── config.py              # Session helper, base URL, set_auth_token()
├── auth/
│   ├── auth.md            # Docs đăng nhập, register, transfer
│   └── auth.py            # auth_with_device_id(), login(), register(), shake_hand()...
├── player/
│   ├── player.md          # Docs player APIs
│   └── player.py          # get_player_info(), check_early_access_code()...
├── game/
│   ├── game.md            # Docs battle flow
│   └── game.py            # game_start(), game_complete(), game_revive()...
├── shop/
│   ├── shop.md            # Docs shop, IAP, gacha, wish list
│   └── shop.py            # get_shop(), buy_shop_item(), buy_iap()...
├── card/
│   └── card.py            # get_all_cards(), upgrade_card(), buy_skin()...
├── deck/
│   └── deck.py            # get_deck(), set_deck(), set_potential()...
├── clan/
│   └── clan.py            # fetch_clan(), clan chat, raid, support...
├── colosseum/
│   └── colosseum.py       # fetch_colosseum(), match, round data...
├── pvp/
│   └── pvp.py             # fetch_pvp_info(), pvp_matching(), rankings...
├── ranking/
│   └── ranking.py         # Tất cả ranking endpoints + unit statistics
├── territory/
│   └── territory.py       # build, upgrade, hunting (điều tra), alchemy...
├── roguelike/
│   └── roguelike.py       # load/save, start/end floor, season info...
├── treasure/
│   └── treasure.py        # equip, exp, overcome, dismantle...
├── accessory/
│   └── accessory.py       # equip, change stat, preset...
├── artifact/
│   └── artifact.py        # crafting, merge, reroll, polish, equip...
├── rift_weapon/
│   └── rift_weapon.py     # upgrade, equip, reroll, crystal...
├── mission/
│   └── mission.py         # missions, post box, season pass...
├── story_mode/
│   └── story_mode.py      # save, chest reward, challenge...
├── decoration/
│   └── decoration.py      # advisor, map skin, login skin, flag, name tag...
└── event/
    └── event.py           # seasonal events, babel, invasion, coupon, stock, kg-marble...
```

---

## Quick Start

```python
from api.config import set_auth_token
from api.auth.auth import auth_with_device_id, login
from api.player.player import get_player_info, check_early_access_code

# 1. Auth với device ID
result = auth_with_device_id("your-device-uuid")

# 2. Login
result = login(device_uuid="your-device-uuid", locale="vi", platform="Android")

# 3. Gọi APIs
player = get_player_info()

# Kiểm tra early access code
result = check_early_access_code("BETA_CODE_HERE")
```

---

## API Categories

### Auth (`/auth/*`)
| Endpoint | Method | Mô tả |
|----------|--------|--------|
| `/auth?id=` | GET | Auth với device ID |
| `/auth/login` | POST | Đăng nhập |
| `/auth/register` | POST | Tạo tài khoản |
| `/auth/shake-hand` | POST | Heartbeat |
| `/auth/transfer/code` | GET | Tạo transfer code |
| `/auth/transfer` | POST | Dùng transfer code |
| `/auth/link` | POST | Link Google/Apple |
| `/auth/xcdSeed` | GET | Xigncode seed |
| `/auth/xcd?cookie=` | GET | Validate Xigncode |
| `/auth/checkPatchVersion` | GET | Check patch version |
| `/auth/getPatchFolder` | GET | Lấy CDN folder |

### Player (`/player/*`)
| Endpoint | Method | Mô tả |
|----------|--------|--------|
| `/player` | GET | Toàn bộ player data |
| `/player/currencies` | GET | Số dư tiền tệ |
| `/player/getInventory` | GET | Inventory |
| `/player/early-access-mode` | GET | Kiểm tra quyền beta |
| `/player/early-access-mode-code?code=` | GET | **Xác thực beta code (server-side)** |
| `/player/building` | GET | Building info |
| `/player/rename` | POST | Đổi tên |
| `/player/heart/recover` | POST | Hồi phục heart |

### Game Battle (`/game/*`)
| Endpoint | Method | Mô tả |
|----------|--------|--------|
| `/game/start` | POST | Bắt đầu trận |
| `/game/complete` | POST | Hoàn thành trận (gửi result) |
| `/game/revive` | POST | Hồi sinh |
| `/game/skip` | POST | Skip màn |
| `/game/eventMode` | GET | Event mode hiện tại |

### Shop (`/shop/*`)
| Endpoint | Method | Mô tả |
|----------|--------|--------|
| `/shop` | GET | Shop data |
| `/shop` | POST | Mua item |
| `/shop/iap` | POST | Xác nhận IAP |
| `/shop/caniap_new` | POST | Validate IAP receipt |
| `/shop/load-custom-pickups` | GET | Custom pickup gacha |
| `/shop/get-treasure-wish-list` | GET | Wish list bảo cụ |

### Clan (`/clan/*`)
| Endpoint | Method | Mô tả |
|----------|--------|--------|
| `/clan` | GET | Clan info |
| `/clan/create` | POST | Tạo clan |
| `/clan/search` | GET | Tìm clan |
| `/clan/chat` | POST | Chat clan |
| `/clan/raid` | GET | Clan raid info |
| `/clan/raid/end` | POST | Kết thúc raid |

### Rankings (`/ranking/*`)
| Endpoint | Method | Mô tả |
|----------|--------|--------|
| `/ranking/ranking?theme=` | GET | Normal stage ranking |
| `/ranking/pvp-ranking?season=` | GET | PvP ranking |
| `/ranking/colosseum-ranking?season=` | GET | Colosseum ranking |
| `/ranking/roguelike-ranking?challenge=` | GET | Roguelike ranking |
| `/ranking/dimension-rift-ranking` | GET | Dimension Rift ranking |
| `/statistics/unit?id=` | GET | Thống kê sử dụng hero |

### Territory (`/territory/*`)
| Endpoint | Method | Mô tả |
|----------|--------|--------|
| `/territory/fetch` | GET | Territory state |
| `/territory/build` | POST | Xây building |
| `/territory/upgrade-building` | POST | Nâng cấp building |
| `/territory/hunting/fetch` | GET | Điều tra state |
| `/territory/hunting/start` | POST | Bắt đầu điều tra |
| `/territory/hunting/end` | POST | Kết thúc điều tra |

### RogueLike (`/rogueLike/*`)
| Endpoint | Method | Mô tả |
|----------|--------|--------|
| `/rogueLike/load-rogueLike-data` | POST | Load save data |
| `/rogueLike/save-rogueLike` | POST | Lưu progress |
| `/rogueLike/startFloor` | POST | Bắt đầu tầng |
| `/rogueLike/endFloor` | POST | Kết thúc tầng |
| `/rogueLike/season-info` | GET | Season info |

---

## Note về Early Access

```
GET /player/early-access-mode-code?code=<CODE>
```

- Code được validate **100% server-side**
- App không chứa hardcoded key nào
- Code phải được dev distribute trực tiếp
- Response: `{ "success": bool, "message": str }`

---

## Note về Servers

| Server | Dùng cho |
|--------|---------|
| `kgc-k8s-1.awesomepiece.com` | Tất cả gameplay APIs |
| `kgc-ranking-1.awesomepiece.com` | Rankings (Colosseum, Hall of Fame, PvP, normal ranking) |
| `kgc-cdn-1.awesomepiece.com/patch/LIVE/` | Patch XML download |
| `axis-game.awesomepiece.com` | Axis Blade collab |
| `isekai-lobbyserver.awesomepiece.com` | I Sekai collab |
