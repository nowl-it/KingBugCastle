# KGC Notifications System

Hệ thống thông báo đa ngôn ngữ tự động dành cho King God Castle (KGC). Hệ thống thu thập thông tin mới nhất từ game (Bản cập nhật App, Bản vá CDN, Thông báo sự kiện) và gửi cảnh báo dạng Push Notification theo thời gian thực tới cộng đồng qua [ntfy.sh](https://ntfy.sh/).

## 🌟 Tính năng nổi bật
* **Tối ưu siêu tốc (Static Translation):** Không phụ thuộc vào API dịch thuật thứ ba. Hệ thống sử dụng từ điển nhúng sẵn (`translations.json`) cho 15 ngôn ngữ, giúp gửi 45+ thông báo chỉ trong vài giây mà không sợ lỗi Rate-Limit.
* **Topics thông minh:** Tách riêng lẻ từng chủ đề (`version`, `patch`, `notices`) theo từng ngôn ngữ.
* **Master Summary:** Tự động tổng hợp nhiều update trong ngày thành 1 thông báo chung ngắn gọn, tránh spam.
* **Tự động bắt nguồn:** Lấy update Client từ APKPure/AppStore, Patch từ AWS S3 CDN của Awesomepiece và Thông báo từ Notion API.

---

## 📡 Cấu trúc Ntfy Topics (Tổng: 46 Topics)

Bạn chỉ cần Subscribe/Theo dõi một topic cụ thể qua App `ntfy` hoặc trình duyệt để nhận thông báo.

### 1. Topic Tổng hợp (Master Topic)
Dành cho người quản trị hoặc người muốn xem tóm tắt toàn bộ mọi thứ:
- `nowl-summary`

### 2. Topic Cộng đồng (Community Topics)
Cấu trúc: `nowl-<ngôn-ngữ>-<hạng-mục>`
(Các ngôn ngữ hỗ trợ: `en, zh, ja, vi, th, de, es, fr, pt, it, ru, ar, id, pl, tr`)

**Các hạng mục:**
* **Phiên bản Client (`version`)**: `nowl-vi-version`, `nowl-en-version`...
* **Bản vá In-game (`patch`)**: `nowl-vi-patch`, `nowl-en-patch`...
* **Thông báo sự kiện (`notices`)**: `nowl-vi-notices`, `nowl-en-notices`...

---

## 📂 Cấu trúc thư mục

```text
notifications/
├── README.md               # Tài liệu hệ thống (File này)
├── TOPICS.md               # Danh sách chi tiết Ntfy Topics cho Cộng đồng
├── config.sh               # Cấu hình chung (NTFY Server, Prefix, Danh sách ngôn ngữ)
├── check_all.sh            # Script Master (Nhạc trưởng điều phối 3 script dưới)
├── check_appstore.sh       # Script quét version mới từ APKPure (Android) & AppStore (iOS)
├── check_notices.sh        # Script lấy thông báo mới nhất từ Backend Notion của KGC
├── check_patch.sh          # Script quét file mới trên CDN của KGC
└── lib/                    # Thư mục phụ trợ
    ├── translations.json        # 🗂️ Từ điển dữ liệu tĩnh 15 ngôn ngữ
    ├── template_sender.py       # 🚀 Core engine gửi thông báo (thay thế translate động)
    ├── generate_translations.py # Script hỗ trợ render file translations.json
    ├── notices_helper.py        # Tool so khớp ID của Notion
    ├── ntfy_send.sh             # Bash helper cho các cảnh báo cơ bản
    └── utils.sh                 # Bash utilities
```

---

## 🚀 Hướng dẫn cài đặt & Chạy

### 1. Yêu cầu hệ thống (Dependencies)
* Hệ điều hành: Linux/macOS có Bash shell.
* Cài đặt `python3` và `curl` trên hệ thống.

### 2. Khởi chạy thủ công
Bạn có thể chạy file Master để kiểm tra:
```bash
cd notifications
./check_all.sh
```

**Dành cho Developer / Debugging:**
Để test thử hệ thống mà không làm phiền người theo dõi ở các Topic chính thức, bạn có thể truyền cờ `--test`:
```bash
./check_all.sh --test
```
Khi có cờ `--test`, tất cả thông báo của 15 ngôn ngữ sẽ được đẩy chung vào một topic duy nhất có tên là `nowl-test`.

### 3. Lưu ý dành riêng cho nền tảng iOS (iPhone/iPad)
Ứng dụng Ntfy Native (tải từ App Store) hiện **chưa hỗ trợ render Markdown** (chữ in đậm/in nghiêng). Để có trải nghiệm hiển thị nội dung đẹp và chuẩn xác nhất:
1. Mở Safari và truy cập vào trang web `ntfy.sh`.
2. Chọn **Share** > **Add to Home Screen (Thêm vào Màn hình chính)**.
3. Sử dụng bản PWA vừa thêm, hỗ trợ đầy đủ Push Notification và Markdown.

### 3. Tự động hoá qua Cron Job
Nên setup Cron job để hệ thống tự quét mỗi 2 tiếng (hoặc theo khung thời gian mong muốn):
```bash
# Mở crontab editor
crontab -e

# Thêm dòng sau để tự quét vào phút 0 của các khung giờ chẵn (0, 2, 4...)
0 */2 * * * /home/nowl/Code/kgc/notifications/check_all.sh >> /tmp/kgc_ntfy.log 2>&1
```

---

## 🛠 Cách hệ thống lưu trữ State (Trạng thái)
Để tránh thông báo bị trùng lặp, hệ thống sử dụng cache cục bộ tại thư mục:
`~/.local/share/kgc_notifications/`

*Nếu bạn muốn "reset" lại từ đầu để hệ thống thông báo lại phiên bản/patch hiện tại, hãy xoá các file bên trong thư mục này.*
