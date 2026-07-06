# Player APIs

## Lấy thông tin player

### GET /player
`GetPlayerInfo()` - lấy toàn bộ PlayerDataResponseModel:
- currencies, inventory, cards, deck, buildings, territory, missions, pass...

### GET /player/other?targetId={id}
`GetOtherPlayerInfo(int targetId)` - xem profile người chơi khác

### GET /player/currencies
`GetPlayerCurrencies()` - lấy số dư các loại tiền tệ

### GET /player/daily-consumed-currencies
`GetPlayerDailyConsumedCurrencies()` - tổng tiền đã tiêu hôm nay

---

## Player inventory

### GET /player/getInventory
Lấy inventory items của player

### POST /player/useInventory
Request body (`UseInventoryRequestModel`):
```json
{
  "itemId": 20050,
  "count": 1
}
```

### POST /player/use-reward-box-inventory-item
Request body (`UseRewardBoxInventoryItemRequestModel`):
```json
{
  "itemId": 50001,
  "count": 1
}
```

### POST /player/use-skin-box-inventory-item
Request body (`UseSkinBoxInventoryItemRequestModel`):
```json
{
  "itemId": 70001,
  "count": 1
}
```

### POST /player/add-inventory-count
Request body (`InventoryCountRequestModel`):
```json
{
  "inventoryType": "gem",
  "count": 100
}
```

---

## Player info management

### POST /player/rename
Request body (`ChangeNicknameRequestModel`):
```json
{
  "name": "NewKingName"
}
```

### POST /player/changeProfileIcon
Request body (`ChangeProfileIconRequestModel`):
```json
{
  "iconId": 10000
}
```

---

## Buildings (lâu đài/công trình)

### GET /player/building
`GetBuildingInfo()` - lấy state tất cả buildings

### POST /player/building/point
`BuyBuildingPoint()` - mua điểm nâng cấp building

### POST /player/building/resetPoint
Request body (`BuildingRequestModel`):
```json
{
  "levels": [1, 2, 3, 4, 5],
  "preset": 0
}
```

### POST /player/building/save
Lưu cấu hình buildings hiện tại

---

## Heart (năng lượng)

### POST /player/heart/recover
`RecoverHeart()` - hồi phục heart bằng gem

---

## Early Access

### GET /player/early-access-mode
`CanEarlyAccessMode()` - kiểm tra player có thể vào early access không

### GET /player/early-access-mode-code?code={code}
`CheckEarlyAccessModeCode(string code)` - xác thực code beta
- Code được validate server-side, không lưu trong app

---

## Tutorial

### POST /player/tutorial/complete
Body: `{ "statusKey": "tutorial_step_id" }`

### POST /player/tutorial/progress-mission
Body: `{ "number": 5 }`

### GET /player/tutorial-status

---

## Daily / Events

### GET /player/dailyAttendanceEvents
Lấy trạng thái điểm danh hằng ngày

### GET /player/surprise-attendance-event
Lấy trạng thái surprise attendance event

### POST /player/surprise-attendance-event-daily-attendance-reward
Nhận phần thưởng điểm danh surprise

### GET /player/year-event
Lấy thông tin Year Event (sự kiện năm)

### GET /player/year-event-attendance-reward
Nhận phần thưởng điểm danh Year Event

### GET /player/year-event-pass-reward
Nhận phần thưởng Pass của Year Event

### POST /player/year-event-buy-pass-point?buyCount={n}
Mua điểm pass Year Event

---

## Journey / Init

### GET /player/journey-reward
Request body (`JourneyRewardRequestModel`):
```json
{ "rewardIndex": 0 }
```

### POST /player/initialize-journey
Reset journey state

---

## Get Login Scene Illust

### GET /player/get-login-scene-illust-data?version={version}
Lấy data ảnh màn hình login theo version

---

## Ad Bonus

### POST /player/ad
Request body (`AdRequestModel`):
```json
{
  "adType": "revive",
  "placement": "game_revive"
}
```

---

## Misc

### GET /player/game-skip-information
Thông tin skip stages

### POST /player/exception?type={type}
Report exception lên server

### POST /player/logClickNotice?version={version}
Log click notice/popup

### POST /player/completeKingGakReturnEvent
Hoàn thành return event
