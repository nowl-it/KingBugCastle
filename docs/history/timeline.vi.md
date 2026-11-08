# Dòng thời gian dự án — Private server King God Castle

Bản ghi theo ngày tháng về hành trình từ "tôi có đọc được dữ liệu game này không?" đến một
private server công khai có client build riêng, dashboard, wiki và một trang chiến lược.

Các con số lấy từ `docs/history/stats.json` (thu thập từ năm nơi lưu phiên chat),
`git log` và chính các commit.

- **Số phiên:** 283 · **Lượt trao đổi:** 44.940 · **Token vào:** 533,1 M · **Token ra:** 16,3 M
- **Commit:** 672 — 2026-07: 93, 08: 264, 09: 284, 10: 24, 11: 7
- **Phiên đầu tiên:** 2026-03-25 · **Phiên cuối được thu thập:** 2026-11

---

## Giai đoạn 0 — Khảo cổ dữ liệu (tháng 3–6/2026)

| Ngày | Cột mốc |
|---|---|
| 2026-03-25 | Phiên agent đầu tiên trong monorepo `KGCentral` — workspace sau này thành `kgc`. |
| 2026-04 | Đào master data: `Strings_*.xml`, bảng unit/skill, atlas sprite. Mọi thứ bắt đầu bằng việc đọc XML, không phải chạy code. |
| 2026-05 | Trích xuất asset client (UnityPy) — chân dung, icon vật phẩm, sprite, bundle. |
| 2026-06-25 | Dựng khung thông báo/giám sát: watcher phiên bản, fetcher notice, topic ntfy cho 15 ngôn ngữ. Mảnh đầu tiên của "giữ người chơi được thông tin". |
| 2026-06-26 | **Private server đầu tiên khởi động.** FastAPI trên `:8080`, heuristic `route_models.json` viết tay, client được patch để trỏ vào đó. |

Khuôn mẫu cho toàn bộ dự án được định hình ở đây: *client là đặc tả, XML là schema, thứ gì
không đọc được thì là mục tiêu để patch.*

## Giai đoạn 1 — Làm client tin (tháng 7/2026)

| Ngày | Cột mốc |
|---|---|
| 2026-07-05 | Diff `xml.bak` với `xml_live`; căn chỉnh master data Cathy (10800–10810); chuỗi bug `Inherit=`. |
| 2026-07-06 | `Initial commit` — docs, kiến trúc gọn, repo bắt đầu ra hình hài. |
| 2026-07-14 | Docs vận hành + tooling skin/treasure/training-dummy; self-host di động. |
| 2026-07-16 | **Trích xuất il2cpp v171.** v171 không có `libil2cpp.so` trên đĩa: XIGNCODE NEO đóng gói và mã hoá nó bên trong packer `.so`. Công thức unpack thành `docs/mftl-extraction.md`. |
| 2026-07-19 | Sự cố `.so` hỏng: 21 byte lạc, trong đó một lệnh `b` ghi đè `mov w8,#-2` bên trong state machine `MoveNext` → đệ quy UniTask vô hạn → tràn stack ở "Loading resources". Bị chẩn đoán sai hai lần là bug IL2CPP trước khi lần ra việc patch tay. Từ đây có luật: **không bao giờ patch tay file lib đem đi ship**. |
| 2026-07-24 | Sprint phủ route: mọi route client v171 ánh xạ đúng response model, kèm shop, mission, territory, Babel, colosseum, điểm danh, clan, cosmetic, thưởng invasion. |
| 2026-07-25 | 100% route client có trả lời; chuyển save giữa thiết bị; trận đấu sống sót khi tắt app; leaderboard; rate limiter không còn cấp phát đến chết process. |
| 2026-07-26 | **Cầu đăng nhập Google**: native hook mở `/glogin`, poller lấy account id rồi gọi `Scene_Login.Auth`. Đa tài khoản thành mặc định. |
| 2026-07-27 | Workflow CI/CD tự build XAPK. NRE "lobby đen" truy về patch `ldr → mov` cho klass — giả thuyết đằng sau bị bác bỏ, patch bị tắt vĩnh viễn. |
| 2026-07-31 | **Deploy OCI công khai** sau `kingbugcastle.id.vn`: Ubuntu 20.04, Python 3.12 từ python-build-standalone, HTTP `:8080` + TLS `:8443`, firewall + NAT. Yêu cầu "không mất một đồng nào" được tuyên bố ở đây. |

## Giai đoạn 2 — Từ "server của ai đó" thành một dịch vụ (tháng 8/2026)

| Ngày | Cột mốc |
|---|---|
| 2026-08-01 | GitHub Actions: `ci.yml` (chạy toàn bộ pytest), `deploy.yml` (deploy key chỉ chạy được một lệnh), `build-xapk.yml` (pipeline release). |
| 2026-08-01 | Giải mã thức tỉnh `potentialTier`: một bậc, `0` = chưa thức tỉnh. Save mặc định từng seed `1` nên mọi hero mới đều hiện sao không có. |
| 2026-08-07 | Bug reset ngày: `tomorrow` được lưu vào save khiến client login lại 1 Hz mãi mãi — 17 request/giây, không exception, logcat im lặng. Nay `tomorrow` luôn được suy ra. |
| 2026-08-08 | Sửa gacha hero thứ nguyên: `overcome` bắt đầu từ 1, trùng thì tăng, và `cardExpResults` là bắt buộc nếu không client hiện sao cũ cho đến khi khởi động lại. |
| 2026-08-13 | **Port v172.0.01.** Firebase `LogEvent` nằm trong `Web.Get` giết callback HTTP giữa đường trên thiết bị không có Play Services — stub cả hai overload. Offset mới, patch mới, endpoint ranking trỏ về loopback. |
| 2026-08-14 | Kiến trúc leaderboard: điểm chiến lực tuần đi kèm `/game/complete` dưới dạng `eliteRankingScore`; server lưu giá trị cao nhất. |
| 2026-08-17 | Điểm tế đàn: hai key (`buildingPoint` / `buildingPoints`) gộp làm một, chặn dưới ở 0. |
| 2026-08-18 | Siết auth: login không có id bị từ chối ở chế độ đa người; `uid` template không bao giờ thành key save. `GET /auth` cấp token để bản cài mới đăng nhập được. Sub-stat trang sức gộp theo key. |
| 2026-08-20 | **Pipeline skin Frieren.** Không phải thêm một dòng XML: clone texture + 19 sprite + prefab + 10 animation clip + illustration, gán render-data key riêng, thêm năm location Addressables. Đồng thời ép CRC asset-bundle về 0 ở bốn vị trí runtime. |
| 2026-08-28 | Player portal trên Caddy + Cloudflare. |
| 2026-08-31 | Lò rèn Dominion. |

## Giai đoạn 3 — Vượt ra ngoài game (tháng 9/2026)

| Ngày | Cột mốc |
|---|---|
| 2026-09-05 | Wiki + quy trình PR. |
| 2026-09-08 | Diff master data republish với bundle trước và xuất bản báo cáo HTML có ảnh minh hoạ. |
| 2026-09-09 | Sửa đồng bộ thứ nguyên (tính năng có nhưng âm thầm không làm gì). |
| 2026-09-12 | Nâng client v173; cái bẫy "il2cpp treo chờ nhấn phím" được ghi vào docs để không tốn token nữa. |
| 2026-09-14 | Phát hiện bất thường tầm skill Farael trong master data chính thức (3 ô → 41 ô ở cấp 3) — chỉ đọc, không sửa. |
| 2026-09-15 | **Strife Compendium**: toàn bộ chiến lược, tarot, luật loại trừ và trình giả lập tỉ lệ roll, đóng gói thành một file HTML song ngữ và đưa lên GitHub Pages. |

## Giai đoạn 4 — Tái dựng (tháng 10/2026)

| Ngày | Cột mốc |
|---|---|
| 2026-10 | Công việc Ghidra + dựng lại project Unity: phục hồi toàn bộ mã nguồn game để debug sâu hơn, kèm CDN monitor và tích hợp Discord. |
| 2026-10-25 | Thiết kế lại dashboard — audit log, quản trị raid, xem log, theme sáng/tối. Hoàn tất Clan Raid cho v174.1.00 và bump client. |
| 2026-10-27 | Build loopback mặc định nhãn *King Local Castle* để phân biệt bản local với bản công khai trên máy. |

## Giai đoạn 5 — Khép lại (tháng 11/2026)

| Ngày | Cột mốc |
|---|---|
| 2026-11-04 | Sửa deploy: đường sync Caddy gây 502. |
| 2026-11-07 | Dọn dẹp và bàn giao: thu thập lịch sử chat từ năm nơi lưu, dọn rác build, viết lại docs, viết blog song ngữ. |

---

## Nhìn lại

Ba bước ngoặt giải thích gần như toàn bộ tiến độ:

1. **Đọc trước khi patch.** Gần như mọi hố nhiều phiên đều bắt đầu bằng một patch đắp lên
   triệu chứng. Gần như mọi bản sửa đều bắt đầu bằng việc decompile đúng hàm.
2. **Suy ra, đừng lưu.** `tomorrow`, gate master data, CRC, offset — thứ gì chép vào state
   rồi cũng cũ đi, rồi lặp vô hạn, crash, hoặc nói dối.
3. **Một key, một đường.** Điểm tế đàn, sub-stat trang sức, fallback auth: biểu diễn trùng
   lặp gây ra đúng những sự cố đó.

Xem `docs/history/lessons.md` cho sổ tay các bẫy, và `docs/blog/` cho bản kể chuyện.
