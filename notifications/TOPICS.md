# Danh sách Ntfy Topics (KGC Notifications)

Dưới đây là danh sách toàn bộ 46 Ntfy topics hiện có trong hệ thống cùng chức năng tương ứng. 
Người dùng chỉ cần theo dõi (subscribe) topic theo cấu trúc URL: `https://ntfy.sh/<tên_topic>` hoặc nhập `<tên_topic>` vào ứng dụng Ntfy trên điện thoại.

## 1. Master Topic (Dành cho Quản trị viên)
- **`nowl-summary`**: Gửi tin nhắn tóm tắt tự động mỗi khi có cập nhật mới (tổng hợp bản cập nhật App, bản vá nội bộ, và thông báo sự kiện trong ngày). Giúp tránh spam thông báo lẻ tẻ.

## 2. Topics Theo Ngôn Ngữ
Có tổng cộng 15 ngôn ngữ được hỗ trợ. Mỗi ngôn ngữ có 3 luồng thông báo riêng biệt tương ứng với 3 loại dữ liệu cập nhật:
1. **`-version`**: Thông báo khi có bản cài đặt mới nhất của game trên Android (APKPure) hoặc iOS (App Store).
2. **`-patch`**: Thông báo khi game tải xuống bản vá dữ liệu nhỏ in-game (Live Patch) mới trên hệ thống máy chủ CDN.
3. **`-notices`**: Thông báo sự kiện, bảo trì, thông tin mới, code quà tặng từ nhà phát hành.

### Bảng Chi Tiết Các Topics (Copy trực tiếp để theo dõi):

| Ngôn ngữ | Version (Bản cài đặt App) | Patch (Bản vá dữ liệu) | Notices (Tin tức sự kiện) |
| :--- | :--- | :--- | :--- |
| **Tiếng Anh (EN)** | `nowl-en-version` | `nowl-en-patch` | `nowl-en-notices` |
| **Tiếng Việt (VI)** | `nowl-vi-version` | `nowl-vi-patch` | `nowl-vi-notices` |
| **Tiếng Trung (ZH)** | `nowl-zh-version` | `nowl-zh-patch` | `nowl-zh-notices` |
| **Tiếng Nhật (JA)** | `nowl-ja-version` | `nowl-ja-patch` | `nowl-ja-notices` |
| **Tiếng Thái (TH)** | `nowl-th-version` | `nowl-th-patch` | `nowl-th-notices` |
| **Tiếng Đức (DE)** | `nowl-de-version` | `nowl-de-patch` | `nowl-de-notices` |
| **Tiếng Tây Ban Nha (ES)**| `nowl-es-version` | `nowl-es-patch` | `nowl-es-notices` |
| **Tiếng Pháp (FR)** | `nowl-fr-version` | `nowl-fr-patch` | `nowl-fr-notices` |
| **Tiếng Bồ Đào Nha (PT)** | `nowl-pt-version` | `nowl-pt-patch` | `nowl-pt-notices` |
| **Tiếng Ý (IT)** | `nowl-it-version` | `nowl-it-patch` | `nowl-it-notices` |
| **Tiếng Nga (RU)** | `nowl-ru-version` | `nowl-ru-patch` | `nowl-ru-notices` |
| **Tiếng Ả Rập (AR)** | `nowl-ar-version` | `nowl-ar-patch` | `nowl-ar-notices` |
| **Tiếng Indonesia (ID)** | `nowl-id-version` | `nowl-id-patch` | `nowl-id-notices` |
| **Tiếng Ba Lan (PL)** | `nowl-pl-version` | `nowl-pl-patch` | `nowl-pl-notices` |
| **Tiếng Thổ Nhĩ Kỳ (TR)** | `nowl-tr-version` | `nowl-tr-patch` | `nowl-tr-notices` |

---

## 3. Developer / Test Topic
Dành cho người phát triển hoặc test hệ thống:
- **`nowl-test`**: Khi script được chạy với cờ `--test`, thay vì phân loại ra 45 topic riêng biệt, **tất cả** các thông báo đa ngôn ngữ sẽ được đẩy chung vào topic này để thuận tiện theo dõi và debug lỗi hiển thị.
- Để sử dụng tính năng này, hãy chạy lệnh: `./check_all.sh --test`

---

**💡 Mẹo sử dụng:** 
- Nếu bạn là người chơi ở Việt Nam và chỉ muốn biết khi nào có thông báo/sự kiện mới, hãy theo dõi: `nowl-vi-notices`.
- Nếu bạn cần canh chừng thời điểm update game, hãy theo dõi cả 2 kênh: `nowl-vi-version` và `nowl-vi-patch`.
- Nếu sử dụng ứng dụng Ntfy trên điện thoại: Bạn hãy nhấn nút `+`, gõ chính xác tên topic mong muốn (vd: `nowl-vi-notices`) và bấm **"Subscribe"**. Mọi cập nhật mới sẽ được gửi ngay lập tức dưới dạng thông báo đẩy (push notification).
