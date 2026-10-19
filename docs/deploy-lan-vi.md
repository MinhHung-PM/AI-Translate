# Chạy site cho đồng nghiệp trong mạng công ty (IP 10.x, không đăng nhập)

Máy của bạn làm máy chủ. Đồng nghiệp trong cùng mạng mở `https://<IP-máy-bạn>`, không cần đăng nhập,
không cần API key: mọi người dùng chung **API key của bạn** (lưu trên máy bạn, không bao giờ gửi tới
trình duyệt). Menu "Cài đặt AI" và nút đăng xuất được ẩn.

## Vì sao là HTTPS?

Trình duyệt chỉ cho dùng **micro và chia sẻ âm thanh màn hình/tab** trên trang HTTPS (hoặc localhost).
`http://10.0.x.x` sẽ không thu âm được. Script dựng sẵn HTTPS trên chính IP của máy bạn bằng Caddy, với
chứng chỉ do một CA nội bộ trên máy bạn cấp (không cần tên miền, không cần Internet chiều vào).

## Chạy (một lệnh)

Yêu cầu: Windows + Docker Desktop đang chạy; máy không ngủ (Settings › Power › Sleep: Never) và
Docker Desktop bật "Start when you sign in".

```powershell
cd AI-Translate
git pull
.\start-lan.cmd
```

`start-lan.cmd` chạy `start-lan.ps1` mà không cần đổi chính sách chạy script của Windows (lỗi
"running scripts is disabled on this system"). Có thể bấm đúp vào file, hoặc chạy trực tiếp
`powershell -ExecutionPolicy Bypass -File .\start-lan.ps1`. Các lệnh khác: `.\start-lan.cmd stop`,
`.\start-lan.cmd backup`, `.\start-lan.cmd start 10.0.1.23`.

Lần đầu script sẽ:
1. Tìm IP mạng nội bộ của máy (10.x / 192.168.x / 172.16–31.x). Sai IP → `.\start-lan.ps1 start 10.0.1.23`.
2. Hỏi **OpenAI API key** (bắt buộc) và **Soniox API key** (tùy chọn, Enter để bỏ qua), rồi tạo
   `.env.lan` (chế độ production, không đăng nhập, khóa mã hóa và mật khẩu database ngẫu nhiên).
   File này chứa key: không chia sẻ, không commit (đã có trong `.gitignore`).
3. Mở firewall Windows cho cổng 80/443 (cần chạy PowerShell **Run as administrator** một lần; nếu
   không, script in sẵn lệnh để bạn tự chạy). Mạng phải là **Private/Domain**, không phải Public.
4. Build và khởi động: PostgreSQL, API, worker, web, Caddy (HTTPS). Tạo sẵn "Dự án chung".
5. In địa chỉ để gửi đồng nghiệp: `https://<IP>`.

Khởi động lại máy: các container tự chạy lại khi Docker Desktop mở (`restart: unless-stopped`).
IP đổi (DHCP): chạy lại `.\start-lan.ps1` — script tự cập nhật địa chỉ. Nên xin IT đặt IP cố định.

## Đồng nghiệp làm gì

- Mở `https://<IP>` bằng **Chrome hoặc Edge**.
- Lần đầu trình duyệt báo "Kết nối không riêng tư": bấm **Nâng cao › Tiếp tục truy cập**. Đã kiểm chứng
  (Chromium): sau bước này micro và chia sẻ âm thanh vẫn hoạt động.
- Muốn bỏ hẳn cảnh báo: tải `http://<IP>/ca.crt` → mở file → **Install Certificate** → Current User →
  "Place all certificates in the following store" → **Trusted Root Certification Authorities** → mở lại
  trình duyệt. (Chứng chỉ gốc này chỉ do máy bạn tạo ra, dùng cho site này.)

## Vận hành

| Việc | Lệnh |
|---|---|
| Dừng site (giữ dữ liệu) | `.\start-lan.ps1 stop` |
| Sao lưu database | `.\start-lan.ps1 backup` → `backups\memohub-<ngày-giờ>.sql` (nên chạy hằng tuần) |
| Đổi API key | sửa `OPENAI_API_KEY` / `SONIOX_API_KEY` trong `.env.lan`, rồi `.\start-lan.ps1` |
| Đổi model dịch/biên bản | `SERVER_AI_MODEL` trong `.env.lan` (mặc định `gpt-4.1-mini`) |
| Xem log | `docker compose -p memohub-lan --env-file .env.lan --profile lan logs --tail=100` |

Trên chính máy bạn có thể dùng `http://localhost:3000` (localhost được trình duyệt coi là an toàn).
Site dev (`.\start.ps1`) và site LAN cùng dùng cổng 3000 trên máy: `start-lan` tự tắt site dev (dữ liệu dev
vẫn giữ). API của site LAN chỉ mở cho máy này ở cổng 18000 (`API_PORT`).

## Lưu ý

- **Mọi người dùng chung một tài khoản "Nhóm dùng chung"**: ai trong mạng mở site cũng thấy và sửa
  được tất cả dự án, cuộc họp, biên bản. Chỉ dùng trong mạng công ty; không mở site ra Internet.
- **Chi phí OpenAI/Soniox tính vào key của bạn**; xem "Chi phí & sử dụng AI". Giới hạn tần suất áp
  dụng theo từng trình duyệt (mặc định 20 lượt AI/phút, 120 đoạn âm thanh/phút).
- Âm thanh đi thẳng từ trình duyệt đồng nghiệp tới OpenAI/Soniox bằng khóa tạm thời ngắn hạn do máy chủ
  cấp: máy đồng nghiệp cần truy cập được `api.openai.com` (và `stt-rt.soniox.com` nếu dùng Soniox).
- Cổng 80/443 bị chương trình khác chiếm (IIS, Skype…): đặt `LAN_HTTPS_PORT` / `LAN_HTTP_PORT` khác trong
  `.env.lan`; địa chỉ thành `https://<IP>:<cổng>`.
