# Chạy thử tích hợp Teams / Zoom / Google Meet (chế độ SANDBOX)

Chế độ này chạy thêm một **máy chủ giả lập** Teams, Zoom và Google Meet trên máy của bạn (cổng 9100).
Bạn bấm thử được toàn bộ luồng **Kết nối → Liên kết cuộc họp → Lấy transcript → Dịch → Biên bản** mà
**không cần tài khoản thật**. Ứng dụng không gửi gì tới Microsoft, Zoom hay Google, và mọi kết nối đều
mang nhãn đỏ **SANDBOX**. Chế độ này chỉ dùng để thử nghiệm; khi `ENVIRONMENT=production`, ứng dụng từ
chối khởi động với cấu hình này.

## 1. Khởi động

Yêu cầu: đã cài và mở **Docker Desktop**.

```bash
./start.sh sandbox          # macOS / Linux
.\start.ps1 sandbox         # Windows PowerShell
```

Đợi đến khi thấy thông báo "Sẵn sàng". Trình duyệt sẽ mở <http://localhost:3000>. Để dừng: `./start.sh stop`
(hoặc `.\start.ps1 stop`).

> Nếu trước đó bạn đã chạy `./start.sh` bản thường thì không cần xóa gì. Lệnh `sandbox` sẽ build lại và
> thêm máy giả lập.

## 2. Kết nối nền tảng

1. Đăng nhập (ví dụ **Nguyễn Văn An (BrSE)** hoặc **Trần Minh (PM)**).
2. Menu trái → **Tích hợp nền tảng**. Bạn sẽ thấy 3 thẻ Teams / Zoom / Google Meet với nhãn **SANDBOX**.
3. Ở thẻ **Zoom**, bấm **Kết nối** → trình hướng dẫn → **Mở trang cấp quyền**. Máy giả lập "đồng ý" ngay
   và đưa bạn quay lại trang với thông báo **Kết nối thành công**. Thẻ chuyển sang
   *Đã kết nối — chỉ sau cuộc họp*.
4. Bấm **Kiểm tra kết nối** và **Chẩn đoán** để xem trạng thái. Không bao giờ hiển thị token.

Làm tương tự với **Teams** và **Google Meet** nếu muốn.

## 3. Lấy transcript cho một cuộc họp

1. **Cuộc họp mới** → chọn dự án (ví dụ ALPHA), **Nền tảng họp** = Zoom → **Tạo cuộc họp**.
   Phần đầu trang sẽ hiện *Zoom · Chưa liên kết cuộc họp*.
2. Trong khung **Nguồn cuộc họp**, dán một trong các mã giả lập dưới đây (hoặc bấm **Tải danh sách**
   rồi chọn), bấm **Liên kết**:

| Nền tảng | Dán vào ô "Link tham gia / ID cuộc họp" |
|---|---|
| Zoom | `https://us02web.zoom.us/j/85746065432` (hoặc `85746065432`) |
| Teams | `https://teams.microsoft.com/l/meetup-join/19%3ameeting_ABC123%40thread.v2/0?context=%7b%7d` |
| Google Meet | `https://meet.google.com/abc-mnop-xyz` (hoặc `abc-mnop-xyz`) |

3. Bấm **Lấy transcript sau cuộc họp**. Sau vài giây, trạng thái chuyển sang **Đã nhập** và bảng transcript
   hiện các đoạn có tên người nói (Zoom: tiếng Anh; Teams: tiếng Nhật).
4. Tiếp tục như bình thường: **Dịch toàn bộ** → **Tạo biên bản AI** → duyệt.

> Mỗi cuộc họp trên nền tảng chỉ liên kết được với **một** cuộc họp trong Memo Hub. Muốn thử lại với cuộc
> họp mới, hãy bấm **Hủy liên kết** ở cuộc họp cũ trước.

## 4. Thử các tình huống lỗi (tùy chọn)

Máy giả lập có thể đóng vai các tình huống thực tế. Chạy lệnh trong terminal, rồi thử lại trên giao diện:

```bash
# Teams: quản trị viên chưa phê duyệt → thẻ hiện "Cần quản trị viên phê duyệt"
curl -X POST "http://localhost:9100/__scenario?provider=teams&name=consent_denied_admin"
# Teams: tenant tắt quyền truy cập transcript
curl -X POST "http://localhost:9100/__scenario?provider=teams&name=transcripts_disabled"
# Zoom: transcript đang xử lý → trạng thái "Đang chờ", tự thử lại
curl -X POST "http://localhost:9100/__scenario?provider=zoom&name=processing"
# Google Meet: cuộc họp quá 30 ngày → "Không có transcript"
curl -X POST "http://localhost:9100/__scenario?provider=google&name=expired"
# Trở lại bình thường (bỏ name)
curl -X POST "http://localhost:9100/__scenario?provider=teams&name="
```

Các tình huống khác: Teams `no_admin_consent`, `no_speaker`, `no_transcript`; Zoom `no_recording`,
`scope_missing`, `rate_limited`; Google `generating`, `ongoing`, `no_transcript`, `no_meet_scope`.
Các tình huống liên quan đến quyền (`consent_denied_admin`, `no_admin_consent`, `no_meet_scope`) có hiệu
lực ở lần **Kết nối lại** tiếp theo.

Trên Windows PowerShell, thay `curl -X POST "..."` bằng `Invoke-WebRequest -Method Post "..."`.

## 5. Không có trong chế độ sandbox

* **Transcript trực tiếp (Zoom RTMS)** hiện *Cần cấu hình*. Tính năng này cần tài khoản Zoom thật đã được
  Zoom bật RTMS, cùng gói SDK `rtms`. Teams và Google Meet không hỗ trợ transcript trực tiếp.
* Màn hình **Trực tiếp / Phát lại** vẫn có chế độ **phát lại demo** (nhãn DEMO) để xem giao diện trực tiếp.

## 6. Chuyển sang tài khoản thật

Khi có tài khoản thật, bạn dừng sandbox, điền thông tin ứng dụng OAuth vào `.env` (`TEAMS_*`, `ZOOM_*`,
`GOOGLE_*`, `PUBLIC_BASE_URL`), để trống `INTEGRATION_*ENDPOINT_OVERRIDES`, rồi chạy `./start.sh` bản
thường. Các bước đăng ký ứng dụng nằm trong [teams.md](teams.md), [zoom.md](zoom.md) và
[google-meet.md](google-meet.md). Lưu ý: Teams cần **quản trị viên tenant phê duyệt** quyền đọc transcript.
