# Việc nên làm tiếp - để dự án trông "chuyên nghiệp"

Danh sách này xếp theo **tỉ lệ giá trị/công sức**, không theo độ hoành tráng. Mục tiêu không
phải làm dự án to hơn, mà làm cho nó *đóng lại được* một cách sạch sẽ: người khác clone về vẫn
hiểu, vẫn build được, và không phải đoán.

Đánh dấu: `S` = dưới 1 giờ · `M` = một buổi · `L` = một ngày trở lên.

---

## Nên làm ngay (đóng gói bàn giao)

### 1. Trang docs đã được deploy - không cần làm gì thêm - `S`
GitHub Pages đã bật (source: branch `main`, thư mục `/docs`, legacy build) và tự dựng lại sau mỗi
push - không cần workflow `pages.yml`. Địa chỉ:
`https://nowl-it.github.io/KingBugCastle/` (landing) · `/blog/` (blog) · `/blog/vi.html`.

Việc duy nhất cần làm: nếu sau này đổi tên repo hoặc chuyển sang custom domain, kiểm tra lại
đường dẫn tương đối trong `docs/index.html` và `docs/blog/*.html` (đều là relative nên chỉ hỏng
khi đổi cấu trúc thư mục, không phải khi đổi domain).

### 2. Tag bản cuối + ghi chú lưu trữ - `S`
```bash
git tag -a v1.0-final -m "Final state: v174.1.00 server, docs, history"
git push origin v1.0-final
```
Thêm 3 dòng ở đầu README: dự án đang ở trạng thái *archived / maintenance*, game version nào
được hỗ trợ lần cuối, và điều kiện để nó chạy lại (bản client nào, patch nào). Một dự án
reverse-engineering "chết" vì không ai biết nó chết từ lúc nào.

### 3. Snapshot những thứ không tái tạo được - `M`
Mọi thứ trong repo đều tái tạo được **trừ** dữ liệu master của đúng phiên bản cuối. Nếu CDN
chính thức đổi hoặc biến mất, `xml_history/` là bản duy nhất còn lại.

- Nén `xml_history/` + `il2cpp/<version>/dump.cs` + `script.json` thành một asset release
  (`master-data-snapshot-<version>.tar.zst`), đính kèm GitHub Release.
- Ghi vào `docs/mftl-extraction.md` một dòng: *"để dựng lại từ đầu, cần đúng bản client
  `<version>` - checksum `…`"*.

### 4. Quét secret trong CI - `S`
`server/secrets/` chứa credential thật và đã nằm trong `.gitignore`, nhưng `.gitignore` chỉ
bảo vệ tương lai. Thêm một job `gitleaks` vào `ci.yml`:

```yaml
- uses: gitleaks/gitleaks-action@v2
```
Nếu nó báo động trên lịch sử cũ thì đó chính là thứ cần biết trước khi public repo rộng hơn.

### 5. Kiểm tra link docs trong CI - `S`
Vừa thêm blog, timeline, README.vi - tức là vừa thêm vài chục đường dẫn tương đối có thể sai.
Một bước `lychee --offline` (hoặc 15 dòng Python) bắt link chết trong `docs/**/*.md` và
`docs/**/*.html`. Rẻ hơn nhiều so với việc người đọc phát hiện hộ.

---

## Nên làm nếu muốn dự án "sống" tiếp

### 6. Một script kiểm tra bất biến của save - `M`
Lớp bug đắt nhất của dự án là *state sai hình dạng* (deck ≠ 6, `potentialTier` = 1, hai key
điểm tế đàn, sub-stat trùng). Hiện mỗi lần chỉ sửa được một ca cụ thể.

Một script `server/tools/audit_players.py` chạy qua `players.db` và báo:
deck length ≠ 6 · card thiếu `unitId` · `potentialTier` ngoài 0..1 · `buildingPoints` còn sót ·
sub-stat trùng key · uid rỗng. Chạy trước mỗi lần deploy. Đây là bản "lint" cho dữ liệu người
chơi, và nó biến từng sự cố đã xảy ra thành một dòng cảnh báo.

### 7. Test cho đường tiền tệ - `M`
Đã có test cho grant/rename/mail. Phần còn thiếu là **idempotency**: nhận thưởng hai lần,
mở reward box hai lần, mua item khi thiếu tiền, mua khi túi đầy. Đây là loại bug người chơi
phát hiện trước bạn và không bao giờ báo đúng chỗ.

### 8. Dashboard: 2FA và phân quyền - `M`
Dashboard đã có auth user/password. Nếu còn chạy công khai, thêm TOTP (một cột trong bảng
`admins` + một ô nhập) và tách quyền *view* / *grant*. Hiện tại ai đăng nhập cũng cấp được
vật phẩm - với một server có người lạ, đó là bề mặt tấn công lớn nhất còn lại.

### 9. Backup có kiểm chứng - `S`
Backup `players.db` đã có. Thiếu bước *kiểm tra backup mở được*: một cron chạy
`sqlite3 backups/latest.db "pragma integrity_check"` và báo Discord nếu fail. Backup không
được test thì không phải backup.

### 10. Đo dung lượng repo - `M`
`.git` đang 1,6 GB, 3.138 file tracked. Nếu muốn repo dễ clone: kiểm tra xem có blob lớn nào
vào git rồi bị xoá (`git rev-list --objects --all | git cat-file --batch-check`). Không cần
`filter-repo` toàn bộ lịch sử, chỉ cần biết cái gì đang chiếm chỗ.

---

## Không nên làm

Đây là phần quan trọng nhất của tài liệu này.

- **Đừng port sang version game mới hơn** trừ khi có người thật sự chơi. Mỗi lần port là một
  tuần disassembly với giá trị sử dụng gần bằng 0 khi server chỉ có một người.
- **Đừng viết lại server bằng ngôn ngữ khác.** Nó chạy, có test, và toàn bộ tri thức nằm
  trong hình dạng hiện tại. Viết lại = dịch lại 700 dòng offset bằng tay.
- **Đừng thêm feature cho dashboard.** Feature đã đủ; thứ thiếu là quyền và audit.
- **Đừng tách `AGENTS.md` / `dev-notes.md` thành wiki nhiều trang.** Chúng dài vì chúng là
  *tra cứu*, và tra cứu thì cần một chỗ để `Ctrl-F`. Một file 731 KB tải trong 200 ms.

---

## Điều kiện dừng

Dự án này nên được coi là **xong** khi:

1. Có tag cuối + một dòng trong README nói rõ nó đang ở trạng thái nào.
2. Người lạ clone về, chạy `python3 setup.py`, và vào được lobby mà không cần hỏi ai.
3. Snapshot master data của version cuối nằm trong một release asset.

Ba điều đó xong thì mọi việc còn lại là sở thích, không phải nghĩa vụ.
