# Brief thiết kế lại UI/UX — Memo Hub (AI Meeting Translator)

Tài liệu này dùng để trao đổi với Claude Design. Phần 1–3 là bối cảnh sản phẩm; phần 4 là prompt dán
thẳng vào Claude Design; phần 5 là những gì cần nhận lại để triển khai vào code.

---

## 1. Sản phẩm là gì

**Memo Hub** là web app nội bộ cho các đội dự án Việt Nam làm việc với khách hàng Nhật Bản. Nó giúp:

1. **Dịch trực tiếp trong cuộc họp**: thu âm thanh từ micro và từ cuộc họp Teams/Zoom/Meet đang chạy trên
   máy, nhận dạng giọng nói, phiên dịch Nhật ↔ Việt (và Anh) **chạy từng chữ khi người nói đang nói**, tách
   người nói.
2. **Biên bản họp bằng AI**: từ transcript, AI soạn biên bản (tóm tắt, quyết định, việc cần làm, vấn đề,
   rủi ro), con người duyệt và chỉnh sửa, rồi xuất file.
3. **Theo dõi công việc** sau họp (action items: người phụ trách, hạn, trạng thái).

Người dùng: PM, BrSE, dev, tester người Việt; một phần hiểu tiếng Nhật hạn chế. Giao diện **100% tiếng
Việt**, nội dung họp chủ yếu **tiếng Nhật và tiếng Việt** (cần font hiển thị tốt cả hai, kể cả dấu tiếng Việt
trên Windows). Dùng trên **Chrome/Edge, Windows, màn hình laptop 1366–1920px**; trong cuộc họp thường mở
song song với Teams/Zoom (cửa sổ hẹp, chia đôi màn hình).

Cách triển khai hiện tại: site nội bộ trong mạng công ty, **không đăng nhập**, mọi người dùng chung một tài
khoản nhóm, API key AI do quản trị viên cài trên máy chủ.

## 2. Bản đồ màn hình và chức năng

Thanh điều hướng trái (8 mục): Tổng quan · Dịch trực tiếp · Cuộc họp mới · Lịch sử cuộc họp · Theo dõi
công việc · Dự án · Chi phí & sử dụng AI · Tích hợp nền tảng. (Cài đặt AI và Quản trị chỉ hiện ở chế
độ có đăng nhập.)

| Màn hình | Đường dẫn | Chức năng chính |
|---|---|---|
| **Tổng quan** | `/` | Bộ lọc (dự án, khoảng ngày, trạng thái, biên bản, người phụ trách); 6 thẻ số liệu (số cuộc họp, biên bản chờ duyệt, việc đang mở, việc quá hạn, vấn đề ưu tiên cao, chi phí AI); cuộc họp gần đây; vấn đề/rủi ro ưu tiên cao; hoạt động gần đây. Nút nhanh "Dịch trực tiếp", "Cuộc họp mới" |
| **Dịch trực tiếp (bắt đầu nhanh)** | `/live` | Chọn dự án → "Bắt đầu ngay" tạo cuộc họp và mở màn hình dịch |
| **Màn hình dịch trực tiếp** ⭐ (quan trọng nhất) | `/meetings/{id}/live` | **Thiết lập** (trước khi bắt đầu): chọn nguồn âm thanh (micro trên máy, có thể nhiều micro; "âm thanh cuộc họp" qua chia sẻ màn hình/tab), đặt tên hiển thị cho từng nguồn; **nhà cung cấp** (OpenAI / Soniox); **chế độ** (Phiên dịch trực tiếp — mặc định; Phụ đề nhanh / cân bằng / chính xác theo câu); ngôn ngữ đầu vào (Tự nhận diện / Chỉ định ja-vi-en); **lọc tạp âm** (Tắt / Tiêu chuẩn / Mạnh); phát giọng đọc bản dịch; checkbox xác nhận đã thông báo người tham gia (bắt buộc). **Khi đang chạy**: trạng thái từng nguồn (mức âm lượng, đang nghe/chặn tạp âm, đã gửi/lỗi, kết nối), danh sách người nói (đổi tên), nút Dừng. **Bảng phụ đề**: bong bóng chat kiểu truyện tranh — bản dịch là dòng chính, lời gốc nhỏ bên dưới, avatar theo người nói, bong bóng "đang nói…" với chữ chạy realtime, nút A−/A+ cỡ chữ, bật/tắt tự cuộn; tab xem dạng bảng. **Kết thúc**: thẻ "Đã kết thúc" + nút Tạo biên bản / Mở biên bản. Còn có tab "Phát lại demo" |
| **Cuộc họp mới** | `/meetings/new` | Form: dự án, tiêu đề, thời gian, múi giờ, loại cuộc họp, ngôn ngữ nguồn/đích/biên bản, người tham gia, mục tiêu, nguồn transcript (nhập file / nền tảng Teams-Zoom-Meet nếu đã kết nối) |
| **Chi tiết cuộc họp (workspace)** | `/meetings/{id}` | Nhập transcript (dán text, file .txt/.vtt/.srt/.docx/.json); bảng transcript song ngữ (thời gian, người nói, lời gốc, bản dịch, trạng thái, sửa tay bản dịch, ghi chú mơ hồ); dịch tất cả / dịch phần chọn / dịch lại / thử lại phần lỗi, thanh tiến độ; tìm kiếm, lọc theo người nói; nút Tạo biên bản; xuất bản ghi |
| **Biên bản** | `/meetings/{id}/memo` | Trạng thái: đang tạo / nháp / chờ duyệt / đã duyệt / bị từ chối. Thông tin cuộc họp; tóm tắt; nội dung thảo luận; câu hỏi mở; cuộc họp tiếp theo; góc nhìn PM (chi phí, phạm vi, chất lượng, tiến độ, leo thang, mức hài lòng khách hàng). Danh sách **Quyết định / Việc cần làm / Vấn đề / Rủi ro**: thêm/sửa/xóa, mỗi mục có mức tin cậy AI, trạng thái xác minh (nháp / cần xem lại / đã xác nhận / bị loại), trích dẫn dòng transcript nguồn (click để xem). Quy trình: Lưu nháp → Gửi duyệt → Duyệt / Từ chối (kèm nhận xét) → Mở lại; Tạo lại bằng AI; xuất Markdown/HTML/JSON |
| **Lịch sử cuộc họp** | `/meetings` | Bảng cuộc họp có tìm kiếm, lọc, sắp xếp, phân trang |
| **Theo dõi công việc** | `/actions` | Bảng action items toàn hệ thống: lọc theo người phụ trách, hạn từ–đến, chỉ của tôi, chỉ quá hạn, trạng thái, ưu tiên; cập nhật trạng thái; link về cuộc họp/nguồn |
| **Dự án** | `/projects`, `/projects/{id}` | Danh sách dự án; chi tiết: thông tin, thời hạn lưu trữ, ngôn ngữ mặc định, chỉ dẫn dịch, **bảng thuật ngữ (glossary)** ja→vi, thành viên |
| **Chi phí & sử dụng AI** | `/usage` | Bộ lọc thời gian; tổng lượt gọi, token, chi phí ước tính; bảng theo thao tác / mô hình / dự án / cuộc họp |
| **Tích hợp nền tảng** | `/integrations` | Thẻ Teams / Zoom / Google Meet: trạng thái (khả dụng / chưa kết nối / chưa cấu hình), kết nối OAuth, liên kết cuộc họp, lấy transcript |
| Cài đặt AI / Quản trị / Đăng nhập | `/settings`, `/admin`, `/login` | Chỉ dùng ở chế độ có đăng nhập (ẩn ở site nội bộ hiện tại) |

## 3. Hiện trạng và vấn đề UX quan sát được

- **Phong cách hiện tại**: chủ đề "ninja/anime" (cam #F97316 + navy, viền đen dày, bóng đổ lệch kiểu
  truyện tranh, nền giấy cuộn, phi tiêu xoay khi tải). Vui mắt nhưng **nặng, nhiều viền, kém chuyên nghiệp**
  khi dùng trong họp với khách hàng, và giảm độ dễ đọc của chữ Nhật/Việt.
- **Màn hình dịch trực tiếp quá tải lúc thiết lập**: có khoảng 7 nhóm tùy chọn (nguồn, nhà cung cấp, chế độ,
  độ trễ, ngôn ngữ, lọc tạp âm, dịch, xác nhận) xếp dọc, nhiều chữ giải thích. Người mới không biết chọn gì;
  thực tế 90% dùng mặc định.
- **Khi đang dịch**: người dùng cần một **khung phụ đề lớn, dễ đọc, ít phân tâm**, thường đặt cạnh cửa sổ
  Teams/Zoom (cửa sổ hẹp 500–700px). Hiện bảng phụ đề và bảng điều khiển nằm chung, chiếm chỗ.
- Trạng thái kỹ thuật (kết nối, mức âm, lỗi, MOCK/SANDBOX) cần **rõ nhưng gọn**.
- Biên bản có rất nhiều khối thông tin, nhiều trạng thái; cần phân cấp rõ, thao tác duyệt rõ ràng.
- Bảng transcript song ngữ dài (hàng trăm dòng): cần dễ quét, dễ sửa bản dịch.
- Điều hướng 8 mục ngang hàng, chưa làm nổi bật luồng chính: **Dịch trực tiếp → Biên bản → Công việc**.

## 4. Prompt cho Claude Design (copy toàn bộ khối dưới)

```text
Bạn là product designer. Hãy thiết kế lại UI/UX cho "Memo Hub" — web app nội bộ giúp đội dự án Việt Nam
họp với khách hàng Nhật: dịch trực tiếp giọng nói Nhật ↔ Việt theo thời gian thực, AI soạn biên bản họp,
và theo dõi việc cần làm. Giao diện tiếng Việt 100%; nội dung họp là tiếng Nhật + tiếng Việt (chọn font
hiển thị tốt cả hai, dấu tiếng Việt không bị lỗi trên Windows, ví dụ "Be Vietnam Pro"/"Inter" + "Noto Sans
JP"). Người dùng: PM, BrSE, dev, tester; dùng Chrome/Edge trên Windows, laptop 1366–1920px, thường mở cạnh
cửa sổ Teams/Zoom.

MỤC TIÊU
1. Chuyên nghiệp, sạch, đáng tin để dùng trong cuộc họp với khách hàng Nhật — thay phong cách hiện tại
   (anime/ninja: cam + navy, viền đen dày, bóng đổ truyện tranh) bằng một design system hiện đại, tối giản,
   vẫn có cá tính nhẹ (giữ màu cam thương hiệu làm accent nếu hợp lý). Có light mode và dark mode.
2. Làm nổi luồng chính: Dịch trực tiếp → Biên bản → Theo dõi công việc.
3. Màn hình "Dịch trực tiếp" là ưu tiên số 1: bắt đầu trong 1–2 thao tác, đọc phụ đề thoải mái suốt 1 giờ họp.

CÁC MÀN HÌNH CẦN THIẾT KẾ (desktop; màn hình Dịch trực tiếp thêm bản cửa sổ hẹp ~600px)
A. Dịch trực tiếp — 3 trạng thái:
   - Thiết lập: chọn nguồn âm thanh (1..n micro; "âm thanh cuộc họp" qua chia sẻ màn hình/tab — cần
     hướng dẫn tick "Chia sẻ âm thanh"), đặt tên hiển thị từng nguồn, checkbox bắt buộc "đã thông báo người
     tham gia", nút Bắt đầu lớn. Các tùy chọn nâng cao gom vào "Tùy chọn nâng cao" (thu gọn mặc định):
     nhà cung cấp (OpenAI / Soniox – rẻ hơn), chế độ (Phiên dịch trực tiếp – mặc định / Phụ đề nhanh /
     cân bằng / chính xác theo câu), ngôn ngữ đầu vào (Tự nhận diện – mặc định / chỉ định ja-vi-en),
     lọc tạp âm (Tắt / Tiêu chuẩn – mặc định / Mạnh), phát giọng đọc bản dịch.
   - Đang dịch: khung phụ đề chiếm phần lớn màn hình. Mỗi câu là một khối: tên + màu/avatar người nói,
     thời điểm, BẢN DỊCH (chữ lớn, dòng chính) và LỜI GỐC (nhỏ, mờ hơn bên dưới). Câu đang nói hiển thị
     chữ chạy realtime từng từ (trạng thái "đang nói…"), không giật layout khi chữ dài ra. Điều khiển gọn:
     A−/A+ cỡ chữ, tự cuộn bật/tắt, chế độ "chỉ bản dịch", chuyển dạng bảng, Dừng. Thanh trạng thái nhỏ
     cho từng nguồn: mức âm lượng, đang nghe / đang chặn tạp âm, kết nối (đang kết nối / đã kết nối /
     kết nối lại / lỗi), số câu đã ghi; lỗi hiển thị rõ nhưng không che phụ đề. Danh sách người nói có
     thể đổi tên ("Người 1" → "Tanaka").
   - Kết thúc: tóm tắt phiên (thời lượng, số câu) + CTA "Tạo biên bản bằng AI" / "Mở biên bản".
B. Biên bản họp: trạng thái (đang tạo / nháp / chờ duyệt / đã duyệt / bị từ chối) và hành động tương ứng
   (Lưu nháp, Gửi duyệt, Duyệt, Từ chối kèm nhận xét, Mở lại, Tạo lại bằng AI, Xuất MD/HTML/JSON). Khối
   nội dung: thông tin cuộc họp, tóm tắt, thảo luận, câu hỏi mở, cuộc họp tiếp theo, góc nhìn PM (chi phí,
   phạm vi, chất lượng, tiến độ, leo thang, hài lòng khách hàng). Bốn danh sách Quyết định / Việc cần làm /
   Vấn đề / Rủi ro: thêm, sửa inline, xóa; mỗi mục có nhãn "AI đề xuất", mức tin cậy, trạng thái xác minh
   (nháp / cần xem lại / đã xác nhận / bị loại) và trích dẫn dòng transcript nguồn (hover/click xem câu
   gốc). Nhấn mạnh: nội dung AI phải được người duyệt.
C. Chi tiết cuộc họp (workspace transcript): nhập transcript (dán text / tải file), bảng song ngữ dài
   hàng trăm dòng (thời gian, người nói, lời gốc, bản dịch có thể sửa, trạng thái dịch, ghi chú mơ hồ),
   dịch tất cả / phần chọn / thử lại phần lỗi với thanh tiến độ, tìm kiếm, lọc người nói.
D. Tổng quan (dashboard): bộ lọc, 6 chỉ số (số cuộc họp, biên bản chờ duyệt, việc đang mở, việc quá hạn,
   vấn đề ưu tiên cao, chi phí AI ước tính), cuộc họp gần đây, vấn đề/rủi ro ưu tiên cao, hoạt động gần
   đây, nút nhanh "Dịch trực tiếp".
E. Theo dõi công việc: bảng việc cần làm có lọc (người phụ trách, hạn, quá hạn, trạng thái, ưu tiên),
   đổi trạng thái nhanh, link về cuộc họp/nguồn.
F. Các màn hình phụ (chỉ cần style guide áp dụng được): Cuộc họp mới (form), Lịch sử cuộc họp (bảng),
   Dự án + bảng thuật ngữ ja→vi, Chi phí & sử dụng AI (bảng + chỉ số), Tích hợp Teams/Zoom/Meet (thẻ trạng
   thái kết nối).

ĐIỀU HƯỚNG
Hiện có 8 mục sidebar: Tổng quan, Dịch trực tiếp, Cuộc họp mới, Lịch sử cuộc họp, Theo dõi công việc,
Dự án, Chi phí & sử dụng AI, Tích hợp nền tảng. Đề xuất cấu trúc gọn hơn, làm nổi "Dịch trực tiếp".
Site nội bộ không đăng nhập (không cần màn hình login/tài khoản).

YÊU CẦU CHUNG
- Trạng thái rỗng, đang tải, lỗi, thành công cho từng màn hình chính.
- Accessibility: tương phản AA, focus rõ, dùng được bàn phím, hỗ trợ prefers-reduced-motion.
- Nhãn trung thực: dữ liệu demo/giả lập phải có badge "MOCK"/"SANDBOX"/"DEMO" rõ ràng.
- Mật độ thông tin vừa phải cho người dùng dân văn phòng; chữ Nhật/Việt cỡ tối thiểu 14px trong bảng,
  phụ đề mặc định ~20–24px.
- Công nghệ triển khai: Next.js + React + Tailwind CSS v4 (design tokens dạng CSS variables), icon
  lucide-react. Ưu tiên component đơn giản, dễ code lại.

KẾT QUẢ MONG MUỐN
1. Design system: màu (light/dark, semantic: success/warning/danger/info), typography (font, cỡ, line-height
   cho ja/vi), spacing, radius, shadow, các component (Button, Input, Select, Checkbox, Radio/segmented,
   Badge, Card, Table, Tabs, Alert, Dialog, Toast, Tooltip, Progress, Empty state, Sidebar).
2. Mockup chi tiết cho A (3 trạng thái + bản cửa sổ hẹp), B, C, D, E; style áp dụng cho F.
3. Ghi chú tương tác: chữ chạy realtime, tự cuộn, chuyển trạng thái, xử lý lỗi kết nối.
Hãy bắt đầu bằng 2–3 hướng phong cách (moodboard ngắn) để tôi chọn, rồi đi sâu vào hướng được chọn,
bắt đầu từ màn hình Dịch trực tiếp.
```

## 5. Mang gì về để triển khai

Khi đã chốt với Claude Design, gửi lại cho Claude Code (trong phiên này) càng nhiều càng tốt:

- **Ảnh chụp/xuất mockup** từng màn hình (PNG), kể cả trạng thái rỗng/lỗi và dark mode.
- **Design tokens**: bảng màu (hex), font, cỡ chữ, spacing, radius, shadow — tốt nhất dạng CSS variables
  hoặc Tailwind theme.
- Nếu Claude Design xuất được **HTML/React/link artifact** thì gửi link — sẽ chuyển thẳng sang component.
- Những thay đổi luồng (ví dụ gom tùy chọn nâng cao, đổi menu) để cập nhật logic + test E2E đi kèm.

Mã nguồn liên quan: `frontend/src/app/globals.css` (tokens hiện tại), `frontend/src/components/ui/*`
(component), `frontend/src/components/layout/app-shell.tsx` (menu), `frontend/src/components/audio/*`
(màn hình dịch trực tiếp), `frontend/src/components/memo/*` (biên bản).
