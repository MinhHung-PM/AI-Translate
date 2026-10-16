# Thu âm & dịch trực tiếp (Live audio capture)

**Ngày xác minh:** 2026-10-16 · **Đã kiểm chứng với OpenAI thật:** **Chưa** (môi trường xây dựng không có
API key). Hợp đồng API được lấy từ đặc tả chính thức `openai/openai-openapi`; mọi test dùng HTTP giả lập
hoặc bộ nhận dạng MOCK.

## Hệ thống làm gì

Màn hình **Trực tiếp / Phát lại → Thu âm trực tiếp** cho phép chọn các nguồn âm thanh trên máy tính, nhận
dạng giọng nói, **tách người nói** và **dịch ngay từng câu** — không cần transcript từ Teams/Zoom/Meet.

```
Trình duyệt (Chrome/Edge)
  nguồn 1: Âm thanh cuộc họp  ← getDisplayMedia: "Toàn màn hình + Chia sẻ âm thanh hệ thống"
                                (ứng dụng Teams/Zoom) hoặc "Tab + Chia sẻ âm thanh tab" (họp trên web)
  nguồn 2..n: Micro            ← getUserMedia (chọn thiết bị cụ thể; có khử vọng/khử ồn)
      │ AudioWorklet → trộn mono → 16 kHz → phát hiện giọng nói (VAD) → mỗi câu 0,3–15 giây
      ▼ POST /audio-sessions/{id}/chunks  (WAV PCM 16-bit, tuần tự theo từng nguồn)
Máy chủ
  OpenAI gpt-4o-transcribe-diarize (response_format=diarized_json)
      + tối đa 4 mẫu giọng (2–10 s) của người nói đã biết → giữ nhãn người nói nhất quán
  → hồ sơ người nói S1, S2… ("Người 1"…; đổi tên được) → ingest_event (chống trùng)
  → dịch ngay bằng nhà cung cấp AI mặc định → màn hình Trực tiếp (cập nhật mỗi giây)
```

### Nhận diện người nói

* **Micro** mặc định là "một người nói": mọi câu gán tên nguồn (ví dụ "Tôi"), không cần tách người nói.
* **Âm thanh cuộc họp** được tách người nói. Lần đầu gặp một giọng mới có ≥ 2 giây âm thanh, hệ thống tạo
  hồ sơ (S1, S2…) và lưu một mẫu giọng ngắn (mã hóa AES-256-GCM). Các đoạn sau gửi kèm tối đa 4 mẫu giọng
  gần nhất để OpenAI trả lại đúng nhãn đó.
* Câu < 2 giây của người chưa biết → **để trống tên** (không bịa người nói).
* Giới hạn: OpenAI chỉ nhận 4 người nói đã biết mỗi lần; người thứ 5 trở lên có thể bị gán thành người mới
  khi quay lại → đổi tên trùng nhau để gộp hiển thị.
* Đổi tên người nói cập nhật lại toàn bộ câu đã có của người đó.

### Độ trễ

Thời gian người nói dứt câu (VAD chờ 0,7 s im lặng) + nhận dạng (thường 1–3 s) + dịch (1–2 s) + tối đa
1 s cập nhật màn hình ≈ **3–6 giây** sau khi dứt câu. Câu dài bị cắt mỗi 15 giây để chữ hiện sớm.

## Cấu hình

1. **Cài đặt AI** → thêm **OpenAI** kèm API key (không cần đặt làm mặc định). Key này dùng cho nhận dạng
   giọng nói; dịch dùng nhà cung cấp mặc định.
2. Không có OpenAI và `ENABLE_MOCK_PROVIDER=true` → chạy **MOCK** (nhãn vàng, văn bản giả lập, không nhận
   dạng thật). Production luôn yêu cầu OpenAI.

| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| `STT_MODEL` | `gpt-4o-transcribe-diarize` | model nhận dạng + tách người nói |
| `STT_TIMEOUT_SECONDS` | `60` | |
| `AUDIO_CHUNK_MAX_SECONDS` / `AUDIO_CHUNK_MAX_BYTES` | `30` / `2000000` | giới hạn mỗi đoạn |
| `AUDIO_MAX_SOURCES` | `4` | số nguồn mỗi phiên |
| `AUDIO_RATE_LIMIT_PER_MINUTE` | `120` | số đoạn/phút/người dùng |
| `AUDIO_SESSION_IDLE_MINUTES` | `30` | phiên không nhận âm thanh quá lâu → tự kết thúc, xóa mẫu giọng |

Chi phí: ghi vào **Chi phí & sử dụng AI** (thao tác "Nhận dạng giọng nói", số giây âm thanh, ước tính theo
giá trong `catalog.json` — 0,006 USD/phút, cần đối chiếu bảng giá OpenAI hiện hành).

## Quyền riêng tư & bảo mật

* Phải tick xác nhận **đã thông báo cho người tham gia** trước khi bắt đầu (lưu thời điểm xác nhận, ghi
  audit `audio_capture.start`).
* **Không lưu file âm thanh.** Âm thanh chỉ nằm trong bộ nhớ khi xử lý. Ngoại lệ duy nhất: mẫu giọng ngắn của
  từng người nói (mã hóa) trong lúc phiên chạy — **xóa khi dừng phiên** hoặc khi phiên bị bỏ dở quá
  `AUDIO_SESSION_IDLE_MINUTES`.
* Dữ liệu gửi tới OpenAI: đoạn âm thanh và mẫu giọng của phiên, tham số ngôn ngữ. Không gửi tên người dùng,
  dự án hay cuộc họp khác.
* Chỉ người bắt đầu phiên được gửi âm thanh vào phiên đó; quyền xem/dừng/đổi tên theo quyền cuộc họp.
* Header `Permissions-Policy` cho phép `microphone` và `display-capture` **chỉ với chính trang ứng dụng**;
  camera và vị trí vẫn bị chặn. AudioWorklet được phục vụ từ cùng origin (CSP giữ `script-src 'self'`).

## Giới hạn & mẹo

* Cần **Chrome hoặc Edge** bản mới; trang mở qua `http://localhost` hoặc HTTPS (trình duyệt chặn micro trên
  HTTP thường).
* "Chia sẻ âm thanh hệ thống" khi chọn **Toàn màn hình** có trên Windows. Trên macOS tùy phiên bản
  Chrome/macOS (chưa kiểm chứng); cách chắc chắn là chia sẻ âm thanh **tab** (họp trên web) hoặc dùng thiết
  bị âm thanh ảo (BlackHole, VB-Cable…) — thiết bị ảo hiện như một micro trong danh sách.
* Dùng **tai nghe**: nếu micro thu lại âm thanh phát từ loa, câu của người khác sẽ bị nhận hai lần.
* Tải lại trang khi đang thu sẽ dừng thu trên trình duyệt; phiên trên máy chủ có nút "Kết thúc phiên đó".
* Nhiều người nói chồng tiếng cùng lúc làm giảm độ chính xác tách người nói.

## Kiểm thử

| Loại | Tệp | Nội dung |
|---|---|---|
| Backend | `backend/tests/test_audio_capture.py` (10) | MOCK: tách/giữ người nói, mic một người nói, câu ngắn không gán tên, chống trùng khi gửi lại, đổi tên, dừng → xóa mẫu giọng; OpenAI (HTTP giả lập theo đặc tả): tham số `model`, `response_format`, `language`, `known_speaker_names[]`, `known_speaker_references[]` (data URL), ánh xạ nhãn, độ lệch thời gian, chi phí; lỗi 401/429 an toàn (không lộ key); WAV không hợp lệ/quá dài/quá lớn; quyền truy cập; xác nhận đồng ý; phiên bỏ dở |
| Frontend | `src/lib/audio/audio.test.ts` (9) | resample 48k/44.1k → 16k, mã hóa WAV, VAD: tách câu theo khoảng lặng, bỏ tiếng click, cắt câu dài, thích nghi tiếng ồn/nhạc nền |
| E2E | `e2e/audio-capture.spec.ts` | Chromium với **micro giả** phát tín hiệu giống giọng nói → phát hiện câu → gửi → nhận dạng (MOCK) → dịch → dừng |

**Chưa kiểm chứng:** chất lượng nhận dạng/tách người nói thật của OpenAI với tiếng Nhật/Việt; chia sẻ âm thanh
hệ thống trên máy Windows thật (getDisplayMedia không tự động hóa được trong test).
