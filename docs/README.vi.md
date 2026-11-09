# KGC Private Server - Cơ sở tri thức vận hành

Playbook thực dụng để **chạy và sửa** private server King God Castle: cấp vật phẩm, mở khoá
nội dung, dựng stage test, sửa master data, và đẩy thay đổi tới client. Đây là tầng
*hướng dẫn vận hành*.

<sub>🇬🇧 <a href="https://github.com/nowl-it/KingBugCastle/blob/main/docs/README.md">Read in English</a></sub>

Nó bổ trợ cho các tài liệu khác - đọc những tài liệu đó để hiểu *vì sao* và *bên trong*:

| Tài liệu | Phạm vi |
|-----|-------|
| **[../HANDOVER.md](https://github.com/nowl-it/KingBugCastle/blob/main/HANDOVER.md)** | Tiếp quản dự án: checklist ngày đầu, công việc định kỳ, sổ tay bẫy, nợ kỹ thuật đã biết |
| **[../README.vi.md](https://github.com/nowl-it/KingBugCastle/blob/main/README.vi.md)** | Trang chủ dự án, danh sách tính năng, bố cục repo |
| **[../SETUP.md](https://github.com/nowl-it/KingBugCastle/blob/main/SETUP.md)** | Chạy lần đầu: clone → `setup.py` → tự chạy server |
| **[../SHARE.md](https://github.com/nowl-it/KingBugCastle/blob/main/SHARE.md)** | Phát hành XAPK đã bake cho người chơi từ xa |
| **[../AGENTS.md](https://github.com/nowl-it/KingBugCastle/blob/main/AGENTS.md)** | Bảng patch nhị phân ARM64, bản đồ RVA, nội bộ il2cpp |
| **[../KNOWLEDGE.md](https://github.com/nowl-it/KingBugCastle/blob/main/KNOWLEDGE.md)** | Tham chiếu datamine: module API, IL2CPP, file master data |
| **[../server/WORKFLOW.md](https://github.com/nowl-it/KingBugCastle/blob/main/server/WORKFLOW.md)** | Vòng lặp sửa/test/deploy hằng ngày, "tôi phải sửa file nào" |

## Thư mục này

| Playbook | Dùng để |
|----------|-----------|
| **[deploy-and-run.md](deploy-and-run.md)** | Khởi động hai server, kết nối thiết bị, đẩy thay đổi tới client |
| **[public-hosting.md](public-hosting.md)** | Chạy nơi người lạ truy cập được: preflight, tài khoản admin, giới hạn lạm dụng, backup |
| **[dashboard-macros.md](dashboard-macros.md)** | Dùng Admin Dashboard để cấp nhanh Macro Profile cho người chơi |
| **[private-build.md](private-build.md)** | Build/chạy client private (v171+, bung XIGNCODE NEO, inject il2cpp, HTTP thay vì TLS) |
| **[mftl-extraction.md](mftl-extraction.md)** | Phục hồi `libil2cpp.so` từ container XIGNCODE NEO (`server/patchers/unpack_neo.py`) |
| **[emulator-note.md](emulator-note.md)** | Ghi chú cho người chơi (VI): vì sao bản gốc v171+ không chạy được trên emulator |
| **[multi-account-login.md](multi-account-login.md)** | Nhiều tài khoản/thiết bị, cầu đăng nhập Google web (`GLOGIN_DEV=1`), mã chuyển tài khoản |
| **[save-editing.md](save-editing.md)** | Cấp tiền tệ / vật phẩm / unit / skin / treasure bằng cách sửa state hoặc gửi thư |
| **[content-unlock.md](content-unlock.md)** | Mở khoá nội dung bị chặn phiên bản (`MinVersion`) - treasure, skin, unit, stage |
| **[stages-and-spawns.md](stages-and-spawns.md)** | Cách định nghĩa quái trong stage; dựng stage training-dummy |
| **[getting-the-data.md](getting-the-data.md)** | Lấy dữ liệu từ đầu: gói client gốc, bundle master data trên CDN (kể cả container mã hoá từ 175+), `dump.cs` |
| **[cdn-master-data.md](cdn-master-data.md)** | Sửa XML master data và đẩy tới client qua bundle xml trên CDN |
| **[discord-cdn-monitor.md](discord-cdn-monitor.md)** | Cấu hình thông báo CDN qua Discord và monitor 30 phút |
| **[api-and-crypto.md](api-and-crypto.md)** | Định dạng AES request/response; gọi server thủ công bằng curl/python |
| **[web-ui-reconstruction.md](web-ui-reconstruction.md)** | Dựng lại UI client thành web UI trung thực bằng IL2CPP, AssetBundle và baseline render |
| **[history/synthesis.md](history/synthesis.md)** | Chín tháng transcript chứa gì: cách vận hành, quyết định, phân loại thất bại, bản đồ tri thức |
| **[history/timeline.vi.md](history/timeline.vi.md)** | Dòng thời gian dự án, theo giai đoạn |
| **[history/lessons.md](history/lessons.md)** | Sổ tay các bẫy: mọi thất bại từng tốn một phiên |
| **[blog/vi.html](blog/vi.html)** | Blog kể chuyện dựng server (VI/EN) |
| **[blog/full.vi.html](blog/full.vi.html)** | Toàn bộ hồ sơ kỹ thuật: từng bước, offset, đoạn code (VI/EN) |
| **[next-steps.md](next-steps.md)** | Việc nên làm tiếp để đóng dự án gọn gàng - và những gì không nên làm (VI) |

## Ngôn ngữ

Mọi trang dành cho người đọc đều song ngữ: `../README.md`/`README.vi.md`, mục lục này,
`README_PLAYER*`, blog (`blog/index.html` + `vi.html`, `blog/full.html` + `full.vi.html`), và
`history/timeline.md` + `timeline.vi.md`. Trang nào có bản song sinh thì link tới nó ở đầu trang.

Tầng tài liệu tham chiếu giữ **chỉ tiếng Anh**: `dev-notes.md`, `history/lessons.md`,
`history/synthesis.md`, `../AGENTS.md`, và các playbook trong thư mục này. Chúng được đọc bởi
người đang ngồi trước log, dịch nửa vời làm cả hai bản tệ đi.

Hai trang **chỉ có tiếng Việt**, cả hai đều ghi `(VI)` trong mục lục ở trên: `next-steps.md`
(lời khuyên cho người vận hành) và `emulator-note.md` (đưa cho người chơi).

## Mô hình tư duy duy nhất giải thích mọi thứ

Có **hai mặt phẳng dữ liệu tách biệt**, và biết thay đổi của mình rơi vào mặt phẳng nào sẽ
tiết kiệm hàng giờ:

1. **State server / phản hồi API** - `server/state/players.db` (SQLite, mỗi người chơi một
   dòng, luôn thông qua `server/playerdb.py`) + các handler trong `server.py` và module route.
   Quyết định *tài khoản game* sở hữu gì và REST API trả về gì (tiền tệ, card, treasure, thư).
   Sửa ở đây có hiệu lực **ngay từng request** (`load_state()` đọc lại dòng mỗi lần gọi) -
   không cần restart, không cần client tải lại.

2. **Master data phía client** - **xml AssetBundle** trên CDN (`server/real_cdn/xml`), dựng từ
   `server/xml_live/*.xml`. Quyết định cái *client* đọc: spawn trong stage, định nghĩa
   skin/unit/treasure, text đã dịch, gate `MinVersion`. Sửa ở đây cần
   `rebuild_xml_bundle.py` → restart server → client tải lại (AssetHash đổi).

> Cấp cho người chơi một treasure = mặt phẳng 1. Làm cho treasure đó *tồn tại / không bị gate*
> với client = mặt phẳng 2. Phần lớn bug "tôi sửa rồi mà không thấy gì" là sửa sai mặt phẳng.
> Xem từng playbook.

### Ranh giới đã biết
- ID unit của người chơi nằm trong khoảng `10000`-`10999`. ID ngoài khoảng này không phải unit
  hợp lệ và có thể làm crash client nếu cấp vào mảng card. `server/playerdb.py` tự lọc bỏ.
- Pool gacha đã bị giới hạn trong khoảng này để tránh cấp unit test hoặc unit của quái.
