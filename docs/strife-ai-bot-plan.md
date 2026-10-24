# KGC Strife Battlefield (Colosseum) Autonomous Vision AI - Project Master Plan

> **Mục tiêu**: Xây dựng một AI độc lập từ bên ngoài (Black-Box Computer Vision Bot) có khả năng tự động chơi chế độ **Strife Battlefield (Đại Đấu Trường / Colosseum)** trên phiên bản **Official Game (Android)**, hoàn thành 100% các quyết định và thao tác chiến thuật trong giới hạn **30 giây** của giai đoạn chuẩn bị (`ReadyPhase`).
>
> **Ràng buộc cốt lõi**:
> 1. **Official Game Safe (Zero-Ban)**: Tuyệt đối không can thiệp bộ nhớ (RAM), không mod APK, không hook runtime để tránh hệ thống chống hack **XIGNCODE3 / AppSign**.
> 2. **30-Second Hard Deadline**: Toàn bộ chu trình từ trinh sát đối thủ, mua quái khắc chế, triệu hồi, ghép sao đến xếp bàn cờ phải hoàn tất dưới **20 - 22 giây** (dành 8 giây đệm an toàn).

---

## 1. Kiến trúc Hệ thống (System Architecture)

```
+-----------------------------------------------------------------------------------+
|                        OFFICIAL ANDROID CLIENT (Stock APK)                        |
|                     (USB 3.0 Debugging / Scrcpy Server / 60 FPS)                  |
+-----------------------------------------------------------------------------------+
       | Video Stream (H.264 Socket: ~20ms)      ^ Virtual Touch (Control Socket: <2ms)
       v                                         |
+------------------------------------+   +------------------------------------------+
| 1. PERCEPTION & VISION ENGINE      |   | 4. FAST ACTION EXECUTION ENGINE          |
| - Scrcpy Frame Grabber             |   | - Low-latency Scrcpy Control Socket      |
| - Grid / Bench ROI Slicer          |   | - Humanized Bezier Curve Gestures        |
| - YOLOv8n / CNN Hero & Star Classif|   | - Gaussian Jitter & Variable Delay       |
| - Fast OCR (Bạc, Timer, HP)        |   | - Emergency Abort & Timeout Watchdog     |
+------------------------------------+   +------------------------------------------+
       | Game State (JSON)                       ^ Action Sequence (Queue)
       v                                         |
+-----------------------------------------------------------------------------------+
| 2. KNOWLEDGE BASE & GAME DATA                                                     |
| - Hero Database (Roles, Star Scaling, Range, Synergies)                           |
| - Strife Compendium (67 Strategies, Tarot Database, Theme 3000 Rules)             |
| - Invade Monster Matrix (Counters, Cost, Spawn Behaviors)                         |
+-----------------------------------------------------------------------------------+
       | Rules & Lookups
       v
+-----------------------------------------------------------------------------------+
| 3. STRIFE DECISION BRAIN (STRATEGY & TACTICS ENGINE)                              |
| [Phase 1: Self Evaluation] -> Carry định hình, Ngưỡng kinh tế giữ lãi (Interest)  |
| [Phase 2: Opponent Scout]  -> Phân loại đối thủ sắp gặp (Archetype Classifier)     |
| [Phase 3: Invade Counter]  -> Mua quái khắc chế điểm yếu đối thủ trong Shop       |
| [Phase 4: Summon & Merge]  -> Tối ưu lượt roll, ghép sao tự động                   |
| [Phase 5: Grid Optimizer]  -> Tọa độ Tanker hàng 1, Carry hàng sau, Buff tile      |
| [Phase 6: Tarot/Strategy]  -> Tự động chọn thẻ bài bổ trợ theo Tier List           |
+-----------------------------------------------------------------------------------+
```

---

## 2. Kế hoạch Phân bổ Thời gian trong 30s (Time Budget)

Để đảm bảo không bao giờ bị trễ khi hết giờ (30s), AI vận hành theo timeline nghiêm ngặt:

| Mốc thời gian | Tác vụ (Task) | Công nghệ / Thao tác | Giới hạn (Max) |
|---|---|---|---|
| **0.0s - 1.5s** | **Phát hiện ReadyPhase** | Quét Icon đồng hồ đếm ngược / Banner chuẩn bị | 1.5s |
| **1.5s - 4.5s** | **Trinh sát Đối thủ (Scouting)** | Click Avatar đối thủ tiếp theo -> Chụp 1 frame -> Đánh giá đội hình đối thủ -> Click về bàn cờ mình | 3.0s |
| **4.5s - 7.5s** | **Invade Shop Counter** | Bấm mở Shop -> Nhận diện 3 quái bán -> Mua quái khắc chế -> Đóng Shop | 3.0s |
| **7.5s - 10.5s** | **Triệu hồi (Summon)** | Kiểm tra Bạc -> Bấm Summon liên tục theo tính toán kinh tế | 3.0s |
| **10.5s - 15.5s** | **Ghép sao (Merge)** | Quét ma trận tướng trùng -> Vuốt ghép sao trên Hàng chờ & Bàn cờ | 5.0s |
| **15.5s - 20.5s** | **Sắp xếp vị trí (Positioning)** | Vuốt đưa Tanker lên Hàng 1, Carry hàng sau, Buffer cạnh Carry, ưu tiên Buff tile | 5.0s |
| **20.5s - 22.0s** | **Chọn Thẻ Tarot / Chiến Lược** | Nếu có popup chọn 3 thẻ -> Chọn thẻ điểm cao nhất | 1.5s |
| **22.0s - 30.0s** | **Đệm An Toàn (Safety Buffer)** | Đứng im chờ Round đấu bắt đầu, hoàn tất 100% | **8.0s đệm** |

---

## 3. Lộ trình Triển khai Dự án (Project Milestones)

Dự án được chia làm **5 Giai đoạn chính (Phases)**:

### Giai đoạn 1: Hạ tầng Stream & Điều khiển Tốc độ cao (Tuần 1)
* **Mục tiêu**: Đạt độ trễ truyền hình ảnh `< 25ms` và độ trễ thao tác cảm ứng `< 3ms`.
* **Công việc cụ thể**:
  1. Xây dựng module kết nối `scrcpy-server` qua socket TCP (H.264/H.265 video stream + Control socket).
  2. Viết công cụ hiệu chuẩn màn hình (`calibration_tool.py`):
     - Xác định độ phân giải màn hình chuẩn (vd: 1920x1080 hoặc 2400x1080).
     - Định vị chính xác tọa độ của:
       + Lưới bàn cờ: 7 cột x 4 hàng (`field_grid[col][row]`).
       + Hàng chờ: 7 ô (`bench_slots[0..6]`).
       + Vị trí nút bấm: Summon, Invade Shop, Reroll, Đóng Shop.
       + Vị trí 4 Avatar người chơi để trinh sát.
  3. Xây dựng engine cảm ứng mượt mà (`human_touch.py`):
     - Thuật toán đường cong Bézier bậc 3 mô phỏng vuốt tay người.
     - Thêm độ lệch ngẫu nhiên Gaussian (±3~7px) và khoảng nghỉ tự nhiên (50~120ms).
* **Tiêu chuẩn nghiệm thu (DoD)**: Gửi được 10 lần click và 5 lần kéo thả liên tục qua socket với độ trễ < 5ms mỗi lệnh, không lỗi đứt kết nối.

---

### Giai đoạn 2: Thị giác Máy tính & Nhận diện Game State (Tuần 2)
* **Mục tiêu**: Trong < 50ms chuyển đổi một khung hình thành dữ liệu JSON cấu trúc đầy đủ.
* **Công việc cụ thể**:
  1. **Thu thập dữ liệu mẫu (Dataset Collection)**:
     - Chụp và cắt mẫu icon của toàn bộ tướng trong Strife (gương mặt đại diện).
     - Thu thập icon cấp sao (1 sao đồng, 2 sao bạc, 3 sao vàng, 4 sao ngọc...).
     - Thu thập icon quái vật Invade Shop.
  2. **Xây dựng Model Nhận diện (Model Training / Inference)**:
     - Huấn luyện mô hình siêu nhẹ **YOLOv8n** hoặc mạng **MobileNetV3 Classifier** chuyên nhận diện Hero + Cấp sao.
     - Sử dụng ONNX Runtime với GPU/DirectML/CPU tăng tốc độ suy luận xuống dưới **15ms / frame**.
  3. **Module OCR số liệu siêu tốc**:
     - Cắt riêng vùng Bạc, Máu, Round, Thời gian đếm ngược.
     - Dùng bộ so khớp mẫu số học (Digit Template Matcher) cực nhanh thay vì OCR nặng nề.
* **Tiêu chuẩn nghiệm thu (DoD)**: Nhận diện chính xác 28 ô bàn cờ và 7 ô hàng chờ đạt độ chính xác > 95% trong thời gian < 40ms.

---

### Giai đoạn 3: Bộ não Chiến thuật Strife (Tactics & Decision Brain) (Tuần 3)
* **Mục tiêu**: Xây dựng thuật toán đưa ra quyết định toàn diện cho trận đấu.
* **Công việc cụ thể**:
  1. **Phân loại vai trò tướng (Hero Archetypes)**:
     - *Main Carry*: Sát thương vật lý (Chung Ah, Mel, Ian, Ren, Cathy, Tia...), Sát thương phép (Yeon, Priya, Kanak...).
     - *Tanker*: Đỡ đòn (Leonhardt, Shelda, Taesan, Behemoth...).
     - *Buffer / Support*: Luniare, Sa-ryung, Mano, Alberon, Lily...
  2. **Phân tích đối thủ sắp gặp (Opponent Analyzer)**:
     - Quét bàn cờ đối thủ để xác định:
       + Đội hình dồn 1 Carry đứng góc hay dàn trải?
       + Đội hình thiên về Sát thương Vật lý hay Phép thuật?
       + Đội hình có Tanker quá trâu hay Hàng sau quá yếu?
  3. **Ma trận Counter Quái Invade Shop**:
     - Tạo ma trận luật:
       - *Đối thủ có Carry tầm xa ở góc* -> Mua quái Sát thủ / Quái dịch chuyển móc lốp.
       - *Đối thủ có Tốc đánh cao (Chung Ah/Ren)* -> Mua quái Giáp gai phản đòn / Giảm tốc đánh / Choáng rộng.
       - *Đối thủ siêu Tank* -> Mua quái Xuyên giáp / Sát thương % máu.
       - *Đối thủ dồn Phép* -> Mua quái Kháng phép / Hút mana / Câm lặng.
  4. **Thuật toán Sắp xếp Bàn cờ (Positioning Algorithm)**:
     - Quy tắc vị trí:
       + Tank xếp Hàng 1 (Frontline).
       + Carry xếp Hàng 3-4 (Backline) ở vị trí xa hướng quái móc lốp nhất.
       + Buffer đứng ô liền kề Main Carry.
       + Ưu tiên đặt tướng vào ô có hiệu ứng bùa (Tile Buff).
  5. **Bộ đánh giá Thẻ Tarot & Chiến Lược**:
     - Tích hợp từ điển `docs/strife-compendium.html` (67 Chiến Lược & Tarot).
     - Chấm điểm Tier list tự động dựa theo đội hình đang sở hữu.
* **Tiêu chuẩn nghiệm thu (DoD)**: Test giả lập (Unit test) 100 tình huống game state, thuật toán đưa ra kế hoạch hành động (Action Plan) hợp lý trong < 10ms.

---

### Giai đoạn 4: Vòng lặp Tự Động Hóa & Chống Phát Hiện (Tuần 4)
* **Mục tiêu**: Ghép nối toàn bộ hệ thống thành vòng lặp tự động từ sảnh chờ đến kết thúc trận.
* **Công việc cụ thể**:
  1. **Cỗ máy Trạng thái (Finite State Machine - FSM)**:
     - `STATE_LOBBY`: Nhận diện sảnh -> Bấm tìm trận Strife.
     - `STATE_MATCH_FOUND`: Chấp nhận trận -> Chờ load màn chơi.
     - `STATE_READY_PHASE`: Kích hoạt quy trình 30 giây (Scout -> Shop -> Summon -> Merge -> Position -> Tarot).
     - `STATE_BATTLE_PHASE`: Theo dõi trận đấu, phân tích sát thương, không thao tác cảm ứng.
     - `STATE_GAME_OVER`: Nhận diện kết quả (Hạng 1-4) -> Bấm Tiếp tục -> Quay về sảnh.
  2. **Watchdog & Fallback Cơ chế Khẩn cấp**:
     - Đặt ngưỡng cứng: Đúng **giây thứ 24**, nếu chưa xong cũng phải lập tức DỪNG TOÀN BỘ thao tác xếp cờ để tránh việc đang kéo dở tướng thì trận đấu bắt đầu làm rơi tướng ra ngoài sân.
* **Tiêu chuẩn nghiệm thu (DoD)**: Bot tự chạy hoàn chỉnh 3 trận Strife liên tục trong phòng Đấu Tùy Chọn (Custom Match) hoặc Trận Thật mà không bị crash hay kẹt vòng lặp.

---

### Giai đoạn 5: Tinh chỉnh & Tối ưu Chiến thuật Nâng cao (Tuần 5+)
* **Mục tiêu**: Tối ưu tỷ lệ thắng (Win Rate) đạt Top 1 - Top 2 ổn định.
* **Công việc cụ thể**:
  1. Thu thập log các trận thua để phân tích sai lầm chiến thuật.
  2. Tinh chỉnh thuật toán quản lý Bạc (Giữ lãi 10/20 Bạc ở các round đầu để tích lũy tài chính).
  3. Cập nhật Meta: Điều chỉnh trọng số các tướng và quái Invade theo bản cập nhật mới nhất của game.

---

## 4. Cấu trúc Thư mục Dự án Đề xuất

```
kgc_strife_bot/
├── config/
│   ├── coordinates_1080p.json    # Tọa độ lưới 7x4, slot, nút bấm
│   ├── hero_tierlist.json        # Phân loại tướng & độ ưu tiên
│   └── invade_counter_rules.json # Ma trận khắc chế quái invade
├── core/
│   ├── scrcpy_stream.py          # Kết nối video stream H.264
│   ├── touch_controller.py       # Điều khiển cảm ứng Bézier mượt mà
│   └── state_machine.py          # FSM điều khiển luồng trận đấu
├── vision/
│   ├── roi_detector.py           # Cắt các vùng quan tâm (ROI)
│   ├── hero_classifier.py        # Nhận diện tướng và số sao (ONNX)
│   ├── ocr_engine.py             # Đọc nhanh Bạc, Máu, Thời gian
│   └── weights/
│       └── strife_heroes_yolo.onnx
├── brain/
│   ├── strategy_engine.py        # Quản lý kinh tế & Main Carry
│   ├── scout_analyzer.py         # Đọc vị đối thủ sắp gặp
│   ├── invade_shopper.py         # Lựa chọn quái counter
│   ├── grid_positioner.py        # Tính toán tọa độ kéo thả tối ưu
│   └── tarot_evaluator.py        # Chọn thẻ từ strife-compendium
├── tools/
│   ├── calibrate_grid.py         # Tool căn chỉnh tọa độ giao diện
│   └── collect_dataset.py        # Tool chụp cắt icon tướng tự động
└── run_bot.py                    # Điểm khởi chạy chính
```

---

## 5. Yêu cầu Môi trường & Thiết bị

1. **Thiết bị chạy Game**:
   - Điện thoại Android cắm cáp USB 3.0 vào PC (Bật USB Debugging), HOẶC
   - Giả lập Android (LDPlayer, BlueStacks, redroid) mở cổng ADB.
2. **Máy tính chạy Bot (Host PC)**:
   - Hệ điều hành: Linux / Windows / macOS.
   - Python 3.10+
   - Thư viện: `opencv-python`, `numpy`, `onnxruntime`, `av` (giải mã video h264), `scrcpy-client`.
   - Card đồ họa (GPU): Khuyến khích NVIDIA GTX 1050 trở lên để chạy inference model ONNX trong 10ms (chạy CPU vẫn khả thi nếu dùng model nano).
