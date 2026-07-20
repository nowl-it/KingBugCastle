# Vì sao King God Castle v171 không mở được trên giả lập

*Ghi chú cho người chơi - cập nhật 2026-07-17*

## Hiện tượng

Từ bản **v171.0.00**, game mở lên là văng ngay, không vào được cả màn đăng nhập. Thử đổi giả lập (BlueStacks, LDPlayer, MEmu, redroid...) đều bị như nhau. Cài lại, xóa cache, đổi bản Android giả lập - không ăn thua.

Đây **không phải máy bạn yếu, không phải cài sai, không phải bản APK hỏng**. Bản v171 cài từ store hoàn toàn nguyên vẹn cũng văng y hệt.

## Nguyên nhân

Từ v171, Awesomepiece đổi lớp bảo vệ chống gian lận sang **XIGNCODE NEO** (của hãng Wellbia). Cơ chế mới:

- File code chính của game (`libil2cpp.so`) không còn nằm sẵn trong APK nữa. Nó bị mã hóa, giấu bên trong một thư viện khác (`libaledatic.so`).
- Lúc khởi động, NEO dùng một kỹ thuật tên **bytehook** để chặn lời gọi nạp thư viện, giải mã code game vào bộ nhớ rồi mới chạy.

Vấn đề: **bytehook không hoạt động được trên giả lập.**

Mọi giả lập Android phổ biến đều chạy trên máy tính x86, phải *dịch* lệnh ARM của game sang x86 (redroid dùng `ndk_translation`, BlueStacks/LDPlayer dùng `libhoudini`). Trên lớp dịch này, bytehook không tìm được thứ nó cần trong bộ nhớ, khởi tạo thất bại. Xem log là thấy rõ:

```
bytehook init ... return: 3        <- lỗi: không khởi tạo được
System.exit called, status: 1      <- game tự thoát
```

Sau đó game tự tắt và bật lại liên tục (crash loop). Nó chết **trước cả khi kết nối tới server**, nên không liên quan gì tới tài khoản hay mạng của bạn.

## Đây là cố ý, không phải lỗi

Việc này xảy ra trên *mọi* giả lập, kể cả bản game gốc chưa ai đụng vào. Nói cách khác: lớp chống gian lận mới của game được thiết kế để **không cho chạy trên giả lập** khi kết nối server chính thống. Đó là quyết định của nhà phát triển, không phải một lỗi sẽ được "vá" ở bản sau.

Sẽ có người rao bán/chia sẻ "bản mod chạy được giả lập + server thật". **Đừng dùng.** Để làm bản đó, người ta phải vô hiệu hóa lớp chống gian lận của game. Ngay khi client bị sửa như vậy, server chính thống phát hiện và **khóa tài khoản** - và người chịu là bạn, không phải người phát bản mod. Bản thân game cũng báo thẳng khi gặp client bị sửa:

> *"File integrity check failed. The account could not be logged in. - Game wasn't installed normally from Google Play"*

## Chơi thế nào

- **Muốn dùng tài khoản thật, nội dung chính thống:** chơi trên **thiết bị Android thật** (điện thoại, máy tính bảng). Lớp bảo vệ chỉ hỏng trên lớp-dịch của giả lập; trên máy ARM thật game chạy bình thường. Đây là cách nhà phát triển muốn game được chơi.
- **Muốn nghịch trên giả lập:** chỉ khả thi với **private server** (server tự dựng), tách hẳn khỏi hệ thống chính thống. Không có tài khoản/xếp hạng chính thống, nhưng không đụng gì tới server thật nên không ai bị khóa. Hướng này đã chạy được: bản v171 private vào tới lobby trên redroid (2026-07-19) - xem [v171-private-build.md](v171-private-build.md).

Không có cách thứ ba. Không có bản mod nào vừa chạy giả lập vừa vào được server chính thống một cách an toàn - vì đúng cái khiến nó văng trên giả lập cũng chính là cái server dùng để kiểm tra client. Sửa cái này là hỏng cái kia.
