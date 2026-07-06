# Shop APIs

## Lấy thông tin shop

### GET /shop
`GetShop()` - lấy toàn bộ ShopResponseModel:
- daily shop items, special packages, gacha info

### POST /shop/refreshDailyShop
`RefreshDailyShop()` - làm mới daily shop (tốn gem)

---

## Mua items

### POST /shop
`BuyShopItem(BuyRequestModel)`

Request body:
```json
{
  "shopItemId": 1001,
  "count": 1,
  "currencyType": "gem"
}
```

---

## IAP (In-App Purchase - mua thật)

### POST /shop/caniap
`CanIAP()` - kiểm tra có thể mua IAP không (validate receipt)

### POST /shop/caniap_new
`CanIAP_New(IAPBuyRequestModel)` - phiên bản mới của CanIAP

Request body:
```json
{
  "productId": "com.awesomepiece.castle.gem1",
  "receipt": "base64_receipt_data",
  "platform": "Android"
}
```

### POST /shop/caniap-and-add-to-restore-needed-iaps
Validate IAP và thêm vào restore list nếu chưa nhận

### POST /shop/iap
`BuyIAP(IAPBuyRequestModel)` - xác nhận mua IAP, nhận items

### GET /shop/get-restore-needed-iaps
Lấy list IAP chưa được restore

### POST /shop/remove-from-restore-needed-iaps
Request body:
```json
{ "receiptId": "receipt_id_string" }
```

---

## Gacha / Custom Pickups

### GET /shop/load-custom-pickups?gachaId={id}
Lấy custom pickup configuration cho gacha cụ thể

### POST /shop/save-custom-pickups
Request body (`CustomPickupsRequestModel`):
```json
{
  "gachaId": 5048,
  "pickups": [30038]
}
```

---

## Treasure Wish List

### GET /shop/get-treasure-wish-list
Lấy danh sách ước muốn treasure (bảo cụ)

### POST /shop/save-treasure-wish-list
Request body (`TreasureWishListRequestModel`):
```json
{
  "wishList": [30001, 30005, 30010]
}
```

### POST /shop/check-treasure-wish-list-valid
Kiểm tra wish list có valid không

---

## Choice Package

### POST /shop/choice-package-unit
Request body (`ChoicePackageUnitRequestModel`):
```json
{
  "shopItemId": 60001,
  "unitId": 10000
}
```
Chọn hero khi mua package có tùy chọn hero

### POST /shop/choice-treasure-pickup-ceil
Request body (`ChoiceTreasurePickupCeilRequestModel`):
```json
{
  "shopItemId": 60000,
  "treasureId": 30038
}
```
Chọn treasure pickup ceiling

---

## Shop Event

### GET /shop-event/cumulative-purchase
Lấy thông tin tích lũy mua hàng

### POST /shop-event/cumulative-purchase/claim
Nhận phần thưởng tích lũy mua hàng
