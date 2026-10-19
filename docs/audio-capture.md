# Thu âm & dịch trực tiếp (Live audio capture)

**Ngày xác minh:** 2026-10-16 (phiên dịch trực tiếp: 2026-10-17) · **Đã kiểm chứng với OpenAI thật:** **Chưa** (môi trường xây dựng không có
API key). Hợp đồng API được lấy từ đặc tả chính thức `openai/openai-openapi`; mọi test dùng HTTP giả lập
hoặc bộ nhận dạng MOCK.

## Phiên dịch trực tiếp (mặc định) — `gpt-realtime-translate`

**Xác minh hợp đồng:** 2026-10-17, từ `openai/openai-openapi` (`POST /realtime/translations/client_secrets`,
sự kiện `session.*`) và cookbook chính thức *"Build Live Translation Apps with gpt-realtime-translate"*
(`openai/openai-cookbook`, 2026-05). **Chưa** chạy với OpenAI thật (môi trường xây dựng không có API key).

| | |
|---|---|
| Cách chạy | Máy chủ cấp client secret tạm thời (`/v1/realtime/translations/client_secrets`, `session.audio.output.language` = ngôn ngữ đích của cuộc họp, `input.transcription.model = gpt-realtime-whisper` để có kèm lời gốc, `noise_reduction` theo cài đặt lọc tạp âm). Trình duyệt gửi SDP tới `https://api.openai.com/v1/realtime/translations/calls`; âm thanh đi thẳng trình duyệt → OpenAI |
| Chữ hiện | **Bản dịch chạy từng chữ** ngay khi đang nói (`session.output_transcript.delta`), lời gốc chạy bên dưới (`session.input_transcript.delta`) |
| Chốt câu | API không có sự kiện "completed": trình duyệt chốt bong bóng khi **ngừng có chữ mới 1,3 s** (bản dịch đã hết câu) hoặc 2,6 s (bản dịch chưa hết câu — người phiên dịch thường nói trễ hơn người nói); bong bóng dài > 160 ký tự được cắt ở dấu hết câu. Câu chốt được lưu kèm **bản dịch của OpenAI** (không dịch lại lần hai, không tốn token dịch) |
| Giọng đọc bản dịch | OpenAI trả cả âm thanh đã dịch; mặc định **tắt**, bật "Phát giọng đọc bản dịch" (nên đeo tai nghe để micro không thu lại) |
| Ngôn ngữ đích hỗ trợ | es, pt, fr, **ja**, ru, zh, de, ko, hi, id, **vi**, it, **en**; đầu vào > 70 ngôn ngữ (tự nhận biết) |

**Giới hạn (theo tài liệu OpenAI):** không hỗ trợ prompt / **bảng thuật ngữ** / danh sách tên — tên riêng và
thuật ngữ có thể bị dịch sai, cần kiểm tra lại; **không tách người nói** trong cùng một nguồn (mỗi nguồn = một
nhãn; muốn tách người, dùng chế độ "Theo câu"); lời nói **đã là ngôn ngữ đích** có thể không có bản dịch → câu
được lưu với lời gốc và đi qua đường dịch thường (trùng ngôn ngữ thì giữ nguyên). Thứ tự lời gốc/bản dịch trong một
bong bóng là gần đúng (hai luồng chữ độc lập). Chi phí phút âm thanh của `gpt-realtime-translate` chưa có trong
`catalog.json` → ghi số giây, chưa ước tính tiền.

## Nhà cung cấp Soniox (tùy chọn, chạy song song với OpenAI)

**Xác minh hợp đồng:** 2026-10-19, từ SDK chính thức của Soniox (`soniox` 2.10.0 trên PyPI — kèm OpenAPI của
API, và `@soniox/speech-to-text-web` 1.4.0). **Chưa** chạy với Soniox thật (không có API key trong môi trường
xây dựng). Giá theo trang của Soniox (06/2026): ≈ $0,12/giờ phụ đề, ≈ $0,18/giờ kèm dịch — tính theo token
nên con số thực tế có thể lệch.

| | |
|---|---|
| Cài đặt | **Cài đặt AI** → thêm **Soniox** + API key. Key cần quyền **Temporary API keys**. Soniox chỉ dùng cho nhận dạng giọng nói — không thể đặt làm nhà cung cấp mặc định (dịch văn bản, biên bản vẫn dùng nhà cung cấp mặc định). "Kiểm tra kết nối" tạo thử một khóa tạm 60 s, không gửi âm thanh |
| Cách chạy | Màn hình Dịch trực tiếp → **Nhà cung cấp: Soniox**. Máy chủ tạo **khóa tạm dùng một lần** (`/v1/auth/temporary-api-key`) và cấu hình phiên; trình duyệt mở `wss://stt-rt.soniox.com/transcribe-websocket`, gửi cấu hình + khóa tạm, rồi gửi âm thanh PCM16 16 kHz (lấy từ cùng chuỗi lọc tạp âm như các chế độ khác) |
| Chế độ | **Phiên dịch trực tiếp**: `translation: one_way` sang ngôn ngữ đích của cuộc họp — lời gốc + bản dịch chạy từng chữ, câu lưu kèm bản dịch của Soniox. **Phụ đề + dịch bằng AI của bạn**: Soniox chỉ nhận dạng, câu hoàn chỉnh dịch bằng nhà cung cấp mặc định |
| Thuật ngữ | Tên người tham gia + thuật ngữ Glossary → `context.terms` (nhận dạng); cặp thuật ngữ Glossary có ngôn ngữ đích của cuộc họp → `context.translation_terms` (dịch); tên dự án → `context.general.domain` |
| Ngôn ngữ / người nói | Tự nhận diện ngôn ngữ (`enable_language_identification`); "Chỉ định ngôn ngữ" → `language_hints`. Tách người nói (`enable_speaker_diarization`) cho nguồn âm thanh cuộc họp; micro "một người nói" thì không |
| Chốt câu | `enable_endpoint_detection`: Soniox gửi token `<end>` khi người nói dứt câu; câu được chốt khi đã có `<end>`, không còn token tạm và (khi dịch) đã có bản dịch. Lưới an toàn: 4 s không có token mới |
| Dừng | Trình duyệt gửi khung rỗng (hết âm thanh), chờ `finished: true` (tối đa 4 s) để không mất chữ cuối |

## Các chế độ phụ đề

| | **Chữ chạy theo lời nói** (mặc định) | **Theo câu** |
|---|---|---|
| Cách chạy | Trình duyệt truyền âm thanh liên tục tới **OpenAI Realtime** qua WebRTC. "Độ trễ phụ đề": **Nhanh nhất / Cân bằng** = `gpt-realtime-whisper` (`delay` minimal/low, `turn_detection: null` — chữ ra trong lúc nói; trình duyệt gửi `input_audio_buffer.commit` khi phát hiện ngắt hơi hoặc tối đa 12 s); **Chính xác theo câu** = `gpt-live-transcribe` (server VAD 350 ms, `languages` + `keywords`). Tự lùi: whisper → live-transcribe → `gpt-4o-transcribe` | Cắt câu trong trình duyệt → gửi từng câu lên máy chủ |
| Chữ hiện | **Ngay khi đang nói** (Nhanh nhất/Cân bằng); bản dịch có khi câu được chốt (ngắt hơi hoặc ≤ 12 s). Nếu OpenAI không gửi "completed", phần chữ đã nhận được lưu sau 7 s không đổi (không mất chữ) | Sau khi dứt câu (+ vài giây) |
| Tách người nói (âm thanh cuộc họp) | Dùng nhãn `speaker` nếu OpenAI gửi sự kiện `transcription.segment`; không có thì để trống | Có, bằng mẫu giọng (≤ 4 người đã biết) |
| Bảo mật | Máy chủ cấp **client secret tạm thời** (hết hạn 10 phút) — API key không rời máy chủ; âm thanh đi thẳng trình duyệt → OpenAI | Âm thanh đi qua máy chủ Memo Hub |
| MOCK (không có OpenAI key) | Không hỗ trợ → tự chuyển sang "Theo câu" | Có |

Chế độ streaming: CSP `connect-src` cho phép thêm `https://api.openai.com` (chỉ để gửi WebRTC offer) và `wss://stt-rt.soniox.com` (Soniox).
Kiểm chứng: `e2e/audio-streaming.spec.ts` dùng một **peer WebRTC giả** đóng vai OpenAI (bắt tay thật trong
Chromium, sự kiện delta/completed theo đặc tả); chưa kiểm chứng với OpenAI thật.

## Hệ thống làm gì

Màn hình **Trực tiếp / Phát lại → Thu âm trực tiếp** cho phép chọn các nguồn âm thanh trên máy tính, nhận
dạng giọng nói, **tách người nói** và **dịch ngay từng câu** — không cần transcript từ Teams/Zoom/Meet.

```
Trình duyệt (Chrome/Edge)
  nguồn 1: Âm thanh cuộc họp  ← getDisplayMedia: "Toàn màn hình + Chia sẻ âm thanh hệ thống"
                                (ứng dụng Teams/Zoom) hoặc "Tab + Chia sẻ âm thanh tab" (họp trên web)
  nguồn 2..n: Micro            ← getUserMedia (chọn thiết bị cụ thể; có khử vọng/khử ồn)
      │ AudioWorklet → trộn mono → 16 kHz → phát hiện giọng nói (VAD) → mỗi câu 0,5–12 giây, cắt tại chỗ ngắt hơi
      ▼ POST /audio-sessions/{id}/chunks  (WAV PCM 16-bit, tuần tự theo từng nguồn)
Máy chủ
  đoạn gần như im lặng (RMS < AUDIO_MIN_RMS) → bỏ qua, không gửi, không tính phí
  Micro / nguồn "một người nói": OpenAI gpt-transcribe (languages[] = ngôn ngữ đã chọn,
      keywords[] = glossary dự án + tên người tham gia); tự lùi về gpt-4o-transcribe nếu tài khoản
      chưa dùng được gpt-transcribe
  Âm thanh cuộc họp (nhiều người): gpt-4o-transcribe-diarize (diarized_json; language chỉ khi chọn
      đúng 1 ngôn ngữ) + tối đa 4 mẫu giọng (2–10 s) → giữ nhãn người nói nhất quán
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

### Chất lượng nhận dạng

* **Ngôn ngữ đầu vào — mặc định "Tự nhận diện"** (`language_detection: "auto"`): không gửi `language` /
  `languages` cho OpenAI; model tự nhận ra ngôn ngữ, kể cả nói xen (vd. từ tiếng Anh trong câu tiếng Nhật).
  Phiên dịch trực tiếp (`gpt-realtime-translate`) luôn tự nhận diện, không có tùy chọn.
* **"Chỉ định ngôn ngữ"** (`"listed"`): model chỉ nhận dạng trong các ngôn ngữ đã chọn → tránh lỗi "ảo giác"
  ra tiếng Tây Ban Nha/Bồ Đào Nha… với đoạn ngắn hoặc phòng ồn. Một ngôn ngữ = chính xác nhất.
* Thêm thuật ngữ và tên riêng vào **Glossary** của dự án và danh sách người tham gia: chúng được gửi làm
  `keywords` để nhận đúng tên người, tên hệ thống.
* Model tách người nói (diarize) chưa hỗ trợ `languages`/`keywords`; với âm thanh cuộc họp, chỉ định đúng một
  ngôn ngữ nếu có thể.
* Nhãn ngôn ngữ của mỗi câu là ngôn ngữ model thực sự nhận ra (không gán theo mặc định của cuộc họp).
* Ghi chú "Lưu ý mơ hồ" của bản dịch luôn viết bằng tiếng Việt.

### Lọc tạp âm tự động

Chọn trên màn hình thu âm: **Tắt / Tiêu chuẩn (mặc định) / Mạnh**. Áp dụng cho **mọi nguồn** (micro và âm
thanh cuộc họp) ngay trong trình duyệt, *trước* khi nhận dạng — cả chế độ chữ chạy lẫn theo câu:

Cổng ồn chạy cho **micro** ở mức Tiêu chuẩn; với **âm thanh cuộc họp / tab** chỉ chạy ở mức Mạnh (Teams, Zoom,
YouTube đã tự lọc ồn — chặn thêm có thể nuốt chữ khi nói nhỏ hoặc có nhạc nền).

1. Lọc thông cao 90 Hz: tiếng ù của quạt, điều hòa, rung bàn.
2. Lọc thông thấp 7,5 kHz: tiếng xì (giọng nói nằm chủ yếu dưới ~7 kHz).
3. **Cổng ồn thích ứng** (`public/audio-worklets/noise-gate.js`): tự học mức ồn nền (mức thấp nhất trong ~3 s)
   và hạ nhỏ âm thanh nằm sát mức đó — Tiêu chuẩn ≈ −18 dB, Mạnh ≈ −30 dB — với attack nhanh/hold/release
   mượt để không cắt đầu/cuối từ. Trên màn hình: "🎙 đang nghe giọng nói" / "🔇 đang chặn tạp âm".
4. Micro: bật thêm bộ lọc ồn của trình duyệt (`noiseSuppression`), luôn bật khử vọng.
5. Chế độ chữ chạy: bật `noise_reduction` của OpenAI (`near_field` cho micro, `far_field` cho âm thanh cuộc
   họp); "Tắt" gửi `null`.

Kiểm thử: `noise-gate.test.ts` chạy chính file worklet — tạp âm nền giảm > 10 dB sau khi thích nghi, giọng nói
giữ nguyên mức (sai lệch < 0,5 dB), mức Mạnh chặn sâu hơn, không cắt 30 ms đầu của từ. Chưa đo trên phòng họp
thật. Cổng ồn giảm tạp âm *giữa* các câu; tạp âm lẫn *cùng lúc* với giọng nói chỉ được giảm một phần (bộ lọc
tần số, bộ lọc của trình duyệt và OpenAI).

### Chống trùng câu khi nhiều nguồn cùng thu một âm thanh

Khi chọn cả âm thanh cuộc họp và micro (micro nghe được loa), Stereo Mix, hoặc cùng một tab hai lần, cùng
một câu được nhận dạng hai lần với chữ hơi khác nhau ("3つ" / "三つ", dấu câu). Máy chủ so sánh mỗi câu mới
với các câu của **nguồn khác** trong ±6 giây (chuẩn hóa NFKC, chữ số Kanji, bỏ dấu câu; độ giống ≥ 0,8) và bỏ
bản trùng — màn hình hiển thị "Bỏ trùng: N". Câu lặp lại trên **cùng một nguồn** (người nói nhắc lại) và câu
rất ngắn ("はい", "ok") không bị coi là trùng.

### Độ trễ

Thời gian người nói dứt câu (VAD chờ 0,65 s im lặng) + nhận dạng (thường 1–3 s, ước tính) + dịch (1–2 s) ≈
**2–5 giây** sau khi dứt câu; màn hình cập nhật ngay khi có kết quả. Người nói liên tục bị cắt tối đa mỗi
12 giây, tại khoảng ngắt nhỏ nhất trong 2 giây cuối (không cắt giữa chữ). (Ước tính — chưa đo với OpenAI thật.)

## Cấu hình

1. **Cài đặt AI** → thêm **OpenAI** kèm API key (không cần đặt làm mặc định). Key này dùng cho nhận dạng
   giọng nói; dịch dùng nhà cung cấp mặc định.
2. Không có OpenAI và `ENABLE_MOCK_PROVIDER=true` → chạy **MOCK** (nhãn vàng, văn bản giả lập, không nhận
   dạng thật). Production luôn yêu cầu OpenAI.

| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| `STT_MODEL` | `gpt-4o-transcribe-diarize` | model nhận dạng + tách người nói (âm thanh cuộc họp) |
| `STT_TEXT_MODEL` / `STT_TEXT_FALLBACK_MODEL` | `gpt-transcribe` / `gpt-4o-transcribe` | model cho nguồn một người nói |
| `AUDIO_MIN_RMS` | `0.004` | ngưỡng âm lượng tối thiểu để gửi đi nhận dạng |
| `STT_REALTIME_MODEL` / `STT_REALTIME_FALLBACK_MODEL` | `gpt-live-transcribe` / `gpt-4o-transcribe` | chế độ chữ chạy |
| `STT_REALTIME_TOKEN_TTL_SECONDS` | `600` | thời hạn client secret tạm thời |
| `SONIOX_MODEL` / `SONIOX_MAX_SESSION_SECONDS` | `stt-rt-v5` / `14400` | model Soniox thời gian thực; thời lượng tối đa mỗi kết nối |
| `STT_INTERPRET_MODEL` / `STT_INTERPRET_INPUT_TRANSCRIPTION_MODEL` | `gpt-realtime-translate` / `gpt-realtime-whisper` | phiên dịch trực tiếp; để trống model thứ hai = không lấy lời gốc |
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
