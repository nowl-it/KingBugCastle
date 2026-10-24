# XIGNCODE Cookie Reverse-Engineering Dossier & AI Handoff Prompt

> **Mục tiêu**: Tự động sinh `cookie` từ `seed` (do `GET /auth/xcdSeed` cấp) để gọi `GET /auth/xcd?cookie=...` lấy `accessToken` chính thức của King God Castle (v174.0.00) hoàn toàn từ Python / PC, không phụ thuộc vào thiết bị di động hay MobileBackup2.

---

## 1. Bản đồ luồng xác thực Client - Server (Đã xác minh 100%)

1. **Lấy Seed**:
   - `GET https://kgc-k8s-1.awesomepiece.com/auth/xcdSeed?version=174.0.00`
   - Headers: `version: 174.0.00`, `platform: IPhonePlayer` (hoặc `Android`), `time: <AES_time>`
   - Response: `HTTP 200 {"code": 200, "success": true, "seed": "<4096-char string>"}`
2. **Sinh Cookie (Client-side native)**:
   - C# `AppSignManager.GetCookie(seed)` (RVA `0x361FC5C`) -> `AppSign.System.GetCookie2(seed)` (RVA `0x2C397E0`)
   - JNI gọi: `com.wellbia.xigncode.AppSignClientSystem.getCookie2(seed)`
   - Native: `libxigncode.so` gọi `ZCWAVE_SendCommand(cmd=0x20, buf, 0x104, seed)`
   - Trả về: `cookie` dạng ASCII string (cấu trúc MITM ghi nhận: `926988XXXX_<md5_fingerprint>_<md5_checksum>`).
3. **Xác thực Cookie để lấy Token**:
   - `GET https://kgc-k8s-1.awesomepiece.com/auth/xcd?cookie=<cookie>`
   - Response khi cookie hợp lệ: `AuthResponseModel` chứa `accessToken` sống!
   - Response khi cookie sai: `HTTP 401 {"code": 401, "msg": "WrongTokenError"}`

---

## 2. Kiến trúc nhị phân XIGNCODE (ARM64 - v174.0.00)

File gốc: `apk/com.awesomepiece.castle@174.0.00.xapk` -> `config.arm64_v8a.apk` -> `lib/arm64-v8a/`

### A. `libxigncode.so` (559 KB) - JNI Shim
- 24 JNI exports, toàn bộ là trampoline sang C++ engine.
- `Java_com_wellbia_xigncode_AppSignClientSystem_ZCWAVE_GetCookie2` @ `0x1EB18`:
  - `cmd = 0x20`, `buf_size = 0x104`.
- `Java_..._GetCooke` (v1) @ `0x1E728` dùng `cmd = 0x1c`.
- Hàm khởi tạo @ `0xFF04`:
  - Tạo chuỗi `"ZCWAVE_SendCommand"` trên stack bằng thuật toán XOR hủy nhau: `key = 0x6e`, `(key+i) ^ mask ^ (key+i)`.
  - Gọi `dlsym(handle, "ZCWAVE_SendCommand")` với `handle` lấy từ `System+8+0x924`.
  - Lưu con trỏ hàm vào atomic slot `System+0x30` (đọc qua `ldar`, ghi qua `stlr` tại `0x10644`). Con trỏ `System*` lưu tại `*(u64*)0x8C0B0` (.bss).

### B. `libgabriel.so` (8.68 MB) - Multi-ELF Container
Là một stub loader 60 byte (.text 60B, SONAME `dummy_symbol`), chứa 3 ELF ARM64 uncompressed được nối liên tiếp:
1. `0x0DF620 .. 0x120620` (266 KB): **`libraphael_barrier.so`** (ELF64 AArch64)
2. `0x120620 .. 0x68D300` (5.68 MB): **`xign_core.so`** (Packed ELF64 AArch64, entry `0x399e0`)
3. `0x6BE620 .. 0x848620` (1.61 MB): **`libsariel.so`** (ELF64 AArch64)

### C. `libraphael_barrier.so` (266 KB) - Intermediate Trampoline & Drop-Loader
- Xuất khẩu 2 hàm: `ZCWAVE_SendCommand` (`0xd388`) và `ZCWAVE_SendCommandVa` (`0xd250`).
- `ZCWAVE_SendCommandVa` @ `0xd250`:
  - Kiểm tra `w8 = cmd - 0x15`. Nếu `w8 > 0xf` -> nhảy tới `0xd2d0`.
  - Jump table tại `0x301A0`: byte values `00 1c 10 10 10 10 3a 10 10 10 10 10 10 10 00 00`.
  - Cả `cmd = 0x1c` (GetCooke) và `cmd = 0x20` (GetCookie2) đều nhảy về **`0xd2d0`**.
  - Tại `0xd2d0`:
    ```arm64
    adrp x8, #0x44000
    ldr  x8, [x8, #0x40]    ; handler = *(u64*)0x44040
    cbz  x8, #error         ; 0xe0190304
    blr  x8                 ; handler(cmd, va_list ap)
    ```
- **Con trỏ `0x44040` được ghi ở đâu?**
  - Ghi duy nhất tại `0x9fd0`: `str x22, [x9, #0x40]`.
  - Trước đó:
    - `0x9d7c`: Gọi hàm `0x96c0` để giải mã payload 5.68 MB từ bộ nhớ.
    - `0x9b2c`: Gọi `fwrite` ghi toàn bộ ELF lõi đã giải mã ra file tạm trên đĩa.
    - `0x9b40`: Gọi `fclose`.
    - `0x9d98`: Gọi `dlopen(temp_so_path, RTLD_NOW)` -> trả về `handle` (x21).
    - `0x9dd8 .. 0x9e48`: Giải mã chuỗi `"ZCWAVE_SendCommandVa"` trên stack bằng XOR key `0x48`.
    - `0x9fa4`: Gọi `dlsym(handle, "ZCWAVE_SendCommandVa")` -> con trỏ x22.
    - `0x9fd0`: Lưu x22 vào `*(u64*)0x44040`.

### D. `xign_core.so` (5.68 MB) - Engine thực tế
- Section header table bị cố tình làm sai lệch để chống `readelf / objdump`.
- Program Headers:
  - `PT_LOAD 0`: Offset `0x0`, VirtAddr `0x0`, FileSiz `0x54a9fc` (R E)
  - `PT_LOAD 1`: Offset `0x54bf90`, VirtAddr `0x54ff90`, FileSiz `0x206d0`, MemSiz `0x29880` (RW)
  - `PT_DYNAMIC`: Offset `0x562db0`, VirtAddr `0x566db0`
- Nơi thực sự xử lý logic cmd `0x20` (nhận `seed` 4096-byte, nhúng device state, băm và xuất ra chuỗi `cookie`).

---

## 3. Bản Prompt bàn giao chuẩn (Sử dụng prompt này cho AI tiếp theo)

Sao chép phần dưới đây để cung cấp cho mô hình AI / Agent RE tiếp theo:

```markdown
Bạn là chuyên gia Reverse Engineering ARM64 và Emulation nhị phân (Unicorn / QEMU / Frida / Android Bionic).
Dự án: King God Castle (v174.0.00). Repo tại /home/nowl/Code/kgc.
Mục tiêu: Xây dựng giải pháp tự động sinh `cookie` từ `seed` (do GET /auth/xcdSeed trả về) để gọi GET /auth/xcd?cookie=<cookie> lấy accessToken từ máy chủ https://kgc-k8s-1.awesomepiece.com.

Bối cảnh và phát hiện kỹ thuật đã chứng minh:
1. Endpoint API:
   - GET /auth/xcdSeed?version=174.0.00 (Public, trả về JSON {"seed": "<4096 ký tự ASCII>"}).
   - GET /auth/xcd?cookie=<cookie> (Cần cookie hợp lệ do XIGNCODE sinh ra, nếu sai trả về 401 WrongTokenError).
2. Chuỗi gọi hàm nhị phân đã map xong 100%:
   - Java_..._GetCookie2 @ 0x1EB18 trong libxigncode.so gọi ZCWAVE_SendCommand(cmd=0x20, buf, 0x104, seed).
   - libgabriel.so (8.68 MB) là container chứa 3 ELF uncompressed:
     * 0xDF620..0x120620: libraphael_barrier.so (266 KB)
     * 0x120620..0x68D300: xign_core.so (5.68 MB)
     * 0x6BE620..0x848620: libsariel.so (1.61 MB)
   - libraphael_barrier.so: ZCWAVE_SendCommandVa @ 0xD250 nhảy tới 0xD2D0 (qua jump table 0x301A0 cho cmd 0x20).
   - Tại 0xD2D0: gọi handler tại *(u64*)0x44040.
   - 0x44040 được nạp tại 0x9FD0 bằng: dlopen(temp_unpacked_so) -> dlsym(handle, "ZCWAVE_SendCommandVa"). Tên hàm được giải mã bằng XOR key 0x48.
   - Thư viện được dlopen chính là xign_core.so sau khi được hàm 0x96C0 giải mã và ghi ra đĩa bằng fwrite (0x9B2C).

File nhị phân đã trích xuất sẵn trong repo:
- .tmp/xign/libxigncode.so (559 KB)
- .tmp/xign/libgabriel.so (8.68 MB)
- .tmp/xign/libraphael_barrier.so (266 KB)
- .tmp/xign/xign_core.so (5.68 MB)
Môi trường Linux hiện tại: x86_64, có sẵn /usr/bin/qemu-aarch64 và /usr/bin/qemu-aarch64-static.

Nhiệm vụ:
Lựa chọn và triển khai 1 trong 2 hướng:
[Phương án 1 - Khuyên dùng: Emulation Loader]:
Dùng Python (Unicorn engine / QEMU arm64 / Android Bionic wrapper) nạp libxigncode.so hoặc gọi trực tiếp ZCWAVE_SendCommand(0x20, out_buf, 0x104, seed) với seed thật lấy từ /auth/xcdSeed để sinh cookie mà không cần dịch ngược bằng tay 5.6MB code.
[Phương án 2 - Static/Dynamic Reversing]:
Phân tích thuật toán mã hóa cmd 0x20 trong xign_core.so để tái tạo logic sinh cookie sang Python thuần.

Hãy bắt đầu bằng việc kiểm tra các file trong .tmp/xign/, phân tích cấu trúc hàm và đề xuất mã chạy thử nghiệm.
```
