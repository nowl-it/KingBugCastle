# Game APIs - Battle flow

## Flow cơ bản

```
POST /game/start  ->  chơi  ->  POST /game/complete
                            ->  POST /game/revive (nếu thua)
                            ->  POST /game/skip (bỏ qua)
```

---

## POST /game/start

`GameStart(GameStartRequestModel)`

Request body:
```json
{
  "theme": 1,
  "currentDeckPreset": 0,
  "difficulty": 3,
  "targetDeck": 0,
  "isArenaTraining": false,
  "foodBoosterLevel": 0,
  "targetBoss": 0,
  "targetDifficulty": 0,
  "isTestBattle": false,
  "isPracticeBattle": false,
  "isRetrying": false,
  "barrackPreset": 0,
  "babelFloor": 0,
  "isEventModeContinued": false,
  "rogueLikeSelectedFirstHero": 0,
  "rogueLikeChallengeLevel": 0,
  "isForceFreeRetry": false,
  "deckInfo": {
    "cards": [10000, 10010, 10020, 10030],
    "buildings": [1, 2, 3, 4, 5],
    "artifacts": []
  },
  "challengeModeDifficulty": 0
}
```

Fields quan trọng:
- `theme`: 1=Normal, 2=Challenge, 4=Story, 6=Babel, 7=Roguelike, v.v.
- `difficulty`: độ khó (1-5 thường)
- `deckInfo.cards`: list unit ID trong deck
- `deckInfo.buildings`: list building levels

Response: `GameStartResponseModel`

---

## POST /game/complete

`GameComplete(GameCompleteRequestModel)`

Request body (cấu trúc phức tạp - gửi kết quả battle lên server):
```json
{
  "roundData": [
    {
      "fieldUnits": [
        {
          "unitId": 10000,
          "level": 30,
          "item1": 0, "item2": 0, "item3": 0, "item4": 0,
          "itemOption1": [], "itemOption2": [], "itemOption3": [], "itemOption4": [],
          "posX": 3, "posY": 2
        }
      ],
      "fieldUnitAIs": "string_ai_data",
      "barricade": 100,
      "cloneUnitRemovedIdx": -1
    }
  ],
  "merchantResult": {
    "item1": 0, "item2": 0, "item3": 0,
    "itemOptions1": [], "itemOptions2": [], "itemOptions3": [],
    "buy1": false, "buy2": false, "buy3": false,
    "hasAd": false
  },
  "develResult": {
    "stage": 0, "condition": "", "reward": 0, "accepted": false
  },
  "craftResult": {
    "item1": 0, "item2": 0, "item3": 0,
    "selectedItem": 0, "reRollCount": 0
  }
}
```

Response: `GameResponseModel` chứa rewards và state mới

---

## POST /game/revive?useReviveCoupon={bool}

`GameRevive(bool useReviveCoupon)`

- `useReviveCoupon=true`: dùng coupon, `false`: dùng gem

---

## POST /game/skip

`GameSkip(GameSkipRequestModel)`

Bỏ qua màn - cần có ticket skip

---

## GET /game/eventMode

`GetEventMode()` - lấy thông tin event mode hiện tại

---

## POST /game/adBonus

`GameAdBonus(GameAdBonusRequestModel)`

Request:
```json
{
  "adType": "gold_bonus",
  "placement": "game_end"
}
```

Nhận bonus sau khi xem quảng cáo

---

## POST /game/check-dimension-rift-complete-success

Kiểm tra kết quả Dimension Rift sau khi hoàn thành
