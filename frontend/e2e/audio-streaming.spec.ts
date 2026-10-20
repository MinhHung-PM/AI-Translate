import { expect, test, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Streaming captions — browser side, against a FAKE "OpenAI Realtime" peer:
// a second RTCPeerConnection in a helper page answers the WebRTC offer and
// sends scripted transcription events over the "oai-events" data channel.
// Our API's session/token/segment endpoints are stubbed for this test (the
// server side is covered by backend tests). No real OpenAI call is made.

// Speech-like fake microphone (syllables + pauses) so the local sentence detector fires.
function speechLikeWav(): string {
  const RATE = 16000;
  const parts: number[] = [];
  const push = (ms: number, amp: number) => {
    for (let i = 0; i < (RATE * ms) / 1000; i++) parts.push(amp * Math.sin((2 * Math.PI * 220 * i) / RATE));
  };
  push(600, 0.001);
  for (let k = 0; k < 6; k++) {
    push(300, 0.4);
    push(90, 0.001);
  }
  push(1500, 0.001);
  const buf = Buffer.alloc(44 + parts.length * 2);
  buf.write("RIFF", 0);
  buf.writeUInt32LE(36 + parts.length * 2, 4);
  buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(RATE, 24);
  buf.writeUInt32LE(RATE * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write("data", 36);
  buf.writeUInt32LE(parts.length * 2, 40);
  parts.forEach((x, i) => buf.writeInt16LE(Math.round(x * 32767), 44 + i * 2));
  const file = path.join(tmpdir(), "memohub-fake-mic-stream.wav");
  writeFileSync(file, buf);
  return file;
}

test.use({
  launchOptions: {
    ...(process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {}),
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${speechLikeWav()}`],
  },
  permissions: ["microphone"],
});

const tid = (page: Page, id: string) => page.getByTestId(id).filter({ visible: true });

test("Streaming captions: interim words appear while speaking, final sentence is stored", async ({ page, context }) => {
  // Fake OpenAI peer.
  const peer = await context.newPage();
  await peer.goto("about:blank");
  const segments: Record<string, unknown>[] = [];

  await page.goto("/login");
  await tid(page, "dev-user").selectOption("pm@example.com");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("heading", { name: "Tổng quan" })).toBeVisible();

  await page.getByRole("link", { name: "Dịch trực tiếp" }).first().click();
  await tid(page, "live-project").selectOption({ label: (await tid(page, "live-project").locator("option", { hasText: /ALPHA/ }).first().textContent()) ?? "" });
  await tid(page, "live-start-now").click();
  await expect(page).toHaveURL(/\/live$/);

  // Stub: the server reports a streaming session (as it does when OpenAI is configured).
  await page.route(/\/api\/v1\/meetings\/[^/]+\/audio-sessions$/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.session.capture_config = { ...body.session.capture_config, mode: "streaming" };
    body.session.is_demo = false;
    await route.fulfill({ response: res, json: body });
  });
  await page.route(/realtime-token$/, (route) =>
    route.fulfill({
      json: { client_secret: "ek_fake", expires_at: 0, model: "gpt-realtime-whisper", client_commits: true, calls_url: "https://api.openai.com/v1/realtime/calls" },
    }),
  );
  await page.route(/\/segments$/, async (route) => {
    segments.push(JSON.parse(route.request().postData() ?? "{}"));
    await route.fulfill({ json: { entries: [], duplicate: false, note: null } });
  });
  let auth = "";
  await page.route("https://api.openai.com/v1/realtime/calls", async (route) => {
    auth = route.request().headers()["authorization"] ?? "";
    const offer = route.request().postData() ?? "";
    const answer = await peer.evaluate(async (sdp) => {
      const pc = new RTCPeerConnection();
      (window as unknown as { pc: RTCPeerConnection }).pc = pc;
      pc.ondatachannel = (ev) => {
        const dc = ev.channel;
        const w = window as unknown as { commits: number };
        w.commits = 0;
        const send = (o: object) => dc.send(JSON.stringify(o));
        // Like gpt-realtime-whisper: text streams while speaking (no item yet, no server VAD)…
        // (Chromium can fire "open" twice — the first one early — on the answering side:
        // script once, after the channel has settled.)
        let scripted = false;
        dc.onopen = async () => {
          if (scripted) return;
          scripted = true;
          await new Promise((r) => setTimeout(r, 500));
          const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
          for (const d of ["Xin ", "chào, ", "tôi ", "tên ", "là "]) {
            send({ type: "conversation.item.input_audio_transcription.delta", delta: d });
            await wait(250);
          }
        };
        // …and an utterance is finalized only when the browser commits it.
        dc.onmessage = (e) => {
          const msg = JSON.parse(String(e.data));
          if (msg.type !== "input_audio_buffer.commit") return;
          w.commits += 1;
          if (w.commits > 1) return;
          setTimeout(() => {
            send({ type: "input_audio_buffer.committed", item_id: "item_A" });
            send({ type: "conversation.item.input_audio_transcription.completed", item_id: "item_A", transcript: "Xin chào, tôi tên là Hùng." });
          }, 2500);
        };
      };
      await pc.setRemoteDescription({ type: "offer", sdp });
      const ans = await pc.createAnswer();
      await pc.setLocalDescription(ans);
      await new Promise<void>((r) => {
        if (pc.iceGatheringState === "complete") return r();
        pc.onicegatheringstatechange = () => pc.iceGatheringState === "complete" && r();
        setTimeout(r, 3000);
      });
      return pc.localDescription!.sdp;
    }, offer);
    await route.fulfill({ status: 201, contentType: "application/sdp", body: answer });
  });

  // Slow server: live-feed polls take 7 s. Interim words must still show immediately.
  await page.route(/\/api\/v1\/meetings\/[^/]+\/live(\?.*)?$/, async (route) => {
    await new Promise((r) => setTimeout(r, 7000));
    await route.continue().catch(() => undefined);
  });
  await tid(page, "unlock-mics").click();
  await tid(page, "mic-list").getByRole("checkbox").first().check();
  await tid(page, "audio-consent").check();
  await tid(page, "advanced-toggle").click();
  await expect(tid(page, "audio-streaming")).toBeChecked();
  await tid(page, "caption-latency").getByRole("radio", { name: "Phụ đề cân bằng" }).click();
  // Captions default to automatic language detection; the language list appears only when asked for.
  await expect(tid(page, "language-detection").getByRole("radio", { name: /Tự nhận diện/ })).toHaveAttribute("aria-checked", "true");
  await expect(tid(page, "audio-languages")).toHaveCount(0);
  await tid(page, "language-detection").getByRole("radio", { name: "Chỉ định ngôn ngữ" }).click();
  await expect(tid(page, "audio-languages")).toBeVisible();
  await tid(page, "language-detection").getByRole("radio", { name: /Tự nhận diện/ }).click();
  await tid(page, "start-audio").click();

  await expect(tid(page, "audio-sources-live")).toContainText("Đang truyền", { timeout: 20_000 });
  await expect(tid(page, "interim-captions")).toContainText("Xin chào, tôi", { timeout: 20_000 });
  await expect.poll(() => segments.length, { timeout: 20_000 }).toBe(1);
  expect(auth).toBe("Bearer ek_fake"); // only the ephemeral secret is sent to OpenAI
  expect(segments[0]).toMatchObject({ item_id: "item_A", text: "Xin chào, tôi tên là Hùng.", model: "gpt-realtime-whisper" });
  expect(Number(segments[0].offset_ms)).toBeGreaterThanOrEqual(0);
  // The local sentence detector told OpenAI where the utterance ended.
  expect(await peer.evaluate(() => (window as unknown as { commits: number }).commits)).toBeGreaterThanOrEqual(1);
  await expect(tid(page, "interim-captions")).toHaveCount(0);

  await tid(page, "stop-audio").click();
  await expect(tid(page, "start-audio")).toBeVisible({ timeout: 30_000 });
});

test("Live interpretation: translated words stream in with the original, sentence stored with its translation", async ({ page, context }) => {
  const peer = await context.newPage();
  await peer.goto("about:blank");
  const segments: Record<string, unknown>[] = [];
  const sessionBodies: Record<string, unknown>[] = [];

  await page.goto("/login");
  await tid(page, "dev-user").selectOption("pm@example.com");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("heading", { name: "Tổng quan" })).toBeVisible();
  await page.getByRole("link", { name: "Dịch trực tiếp" }).first().click();
  await tid(page, "live-project").selectOption({ label: (await tid(page, "live-project").locator("option", { hasText: /ALPHA/ }).first().textContent()) ?? "" });
  await tid(page, "live-start-now").click();
  await expect(page).toHaveURL(/\/live$/);

  await page.route(/\/api\/v1\/meetings\/[^/]+\/audio-sessions$/, async (route) => {
    sessionBodies.push(JSON.parse(route.request().postData() ?? "{}"));
    const res = await route.fetch();
    const body = await res.json();
    body.session.capture_config = { ...body.session.capture_config, mode: "interpret" };
    body.session.is_demo = false;
    await route.fulfill({ response: res, json: body });
  });
  await page.route(/realtime-token$/, (route) =>
    route.fulfill({
      json: {
        client_secret: "ek_tr_fake",
        expires_at: 0,
        model: "gpt-realtime-translate",
        client_commits: false,
        kind: "translation",
        target_language: "vi",
        calls_url: "https://api.openai.com/v1/realtime/translations/calls",
      },
    }),
  );
  await page.route(/\/segments$/, async (route) => {
    segments.push(JSON.parse(route.request().postData() ?? "{}"));
    await route.fulfill({ json: { entries: [], duplicate: false, note: null } });
  });
  let auth = "";
  await page.route("https://api.openai.com/v1/realtime/translations/calls", async (route) => {
    auth = route.request().headers()["authorization"] ?? "";
    const offer = route.request().postData() ?? "";
    const answer = await peer.evaluate(async (sdp) => {
      const pc = new RTCPeerConnection();
      (window as unknown as { pc: RTCPeerConnection }).pc = pc;
      pc.ondatachannel = (ev) => {
        const dc = ev.channel;
        const send = (o: object) => dc.send(JSON.stringify(o));
        // Like gpt-realtime-translate: append-only source + translated deltas, no "completed".
        let scripted = false;
        dc.onopen = async () => {
          if (scripted) return;
          scripted = true;
          await new Promise((r) => setTimeout(r, 500));
          const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
          send({ type: "session.created", session: {} });
          const script: [string, string][] = [
            ["session.input_transcript.delta", "皆さん、"],
            ["session.output_transcript.delta", "Xin chào "],
            ["session.input_transcript.delta", "こんにちは。"],
            ["session.output_transcript.delta", "mọi người"],
            ["session.output_transcript.delta", "."],
          ];
          let elapsed = 0;
          for (const [type, delta] of script) {
            elapsed += 200;
            send({ type, delta, elapsed_ms: elapsed });
            await wait(400);
          }
        };
      };
      await pc.setRemoteDescription({ type: "offer", sdp });
      const ans = await pc.createAnswer();
      await pc.setLocalDescription(ans);
      await new Promise<void>((r) => {
        if (pc.iceGatheringState === "complete") return r();
        pc.onicegatheringstatechange = () => pc.iceGatheringState === "complete" && r();
        setTimeout(r, 3000);
      });
      return pc.localDescription!.sdp;
    }, offer);
    await route.fulfill({ status: 201, contentType: "application/sdp", body: answer });
  });

  await tid(page, "unlock-mics").click();
  await tid(page, "mic-list").getByRole("checkbox").first().check();
  await tid(page, "audio-consent").check();
  await tid(page, "advanced-toggle").click();
  // Live interpretation is the default streaming mode.
  await expect(tid(page, "caption-latency").getByRole("radio", { name: /Phiên dịch trực tiếp/ })).toHaveAttribute("aria-checked", "true");
  await expect(tid(page, "play-voice")).not.toBeChecked();
  // Interpretation always detects the input language: no language picker.
  await expect(tid(page, "audio-languages-auto")).toBeVisible();
  await expect(tid(page, "audio-languages")).toHaveCount(0);
  await tid(page, "start-audio").click();

  await expect(tid(page, "interim-captions")).toContainText("Xin chào", { timeout: 20_000 });
  await expect(tid(page, "interim-original")).toContainText("皆さん");
  await expect.poll(() => segments.length, { timeout: 20_000 }).toBe(1);
  expect(sessionBodies[0]).toMatchObject({ mode: "interpret", caption_latency: "balanced", language_detection: "auto" });
  expect(auth).toBe("Bearer ek_tr_fake");
  expect(segments[0]).toMatchObject({
    text: "皆さん、こんにちは。",
    translated_text: "Xin chào mọi người.",
    model: "gpt-realtime-translate",
  });
  expect(String(segments[0].item_id)).toMatch(/^tr-/);
  await expect(tid(page, "interim-captions")).toHaveCount(0);

  await tid(page, "stop-audio").click();
  await expect(tid(page, "start-audio")).toBeVisible({ timeout: 30_000 });
});

test("Soniox: live words + translation over the WebSocket, sentence stored with Soniox's translation", async ({ page }) => {
  const segments: Record<string, unknown>[] = [];
  const sessionBodies: Record<string, unknown>[] = [];
  const wsLog = { config: null as Record<string, unknown> | null, audioBytes: 0, ended: false };

  // The user has a Soniox key (stubbed before the app loads, which fetches it on mount).
  await page.route(/\/api\/v1\/providers\/configs$/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.push({ id: "00000000-0000-0000-0000-00000000500a", provider: "soniox", model: "stt-rt-v5", is_default: false, has_usable_key: true, key_storage: "persistent" });
    await route.fulfill({ response: res, json: body });
  });
  // Registered before the app loads: Playwright hooks WebSockets created by pages opened afterwards.
  // Fake Soniox real-time WebSocket (token stream per the official SDK contract).
  await page.routeWebSocket("wss://stt-rt.soniox.com/transcribe-websocket", (ws) => {
    let scripted = false;
    ws.onMessage(async (msg) => {
      if (typeof msg === "string") {
        if (msg === "") {
          wsLog.ended = true;
          ws.send(JSON.stringify({ tokens: [], finished: true }));
          return;
        }
        wsLog.config = JSON.parse(msg);
        return;
      }
      wsLog.audioBytes += msg.length;
      if (scripted || wsLog.audioBytes < 16000) return; // start once ~0.5 s of PCM16 arrived
      scripted = true;
      const o = (text: string, is_final: boolean, start_ms: number, end_ms: number) => ({ text, is_final, start_ms, end_ms, speaker: "1", translation_status: "original" });
      const tr = (text: string, is_final: boolean) => ({ text, is_final, translation_status: "translation" });
      const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
      // Slow enough for the assertions to observe each interim state.
      ws.send(JSON.stringify({ tokens: [o("前提", true, 100, 400), o("を確認", false, 400, 700)] }));
      await wait(1500);
      ws.send(JSON.stringify({ tokens: [o("を確認しましょう。", true, 400, 1500), tr("Hãy xác", false), { text: "<end>", is_final: true }] }));
      await wait(2000); // translation trails the endpoint (below the 4 s safety net)
      ws.send(JSON.stringify({ tokens: [tr("Hãy xác nhận giả định.", true)] }));
    });
  });


  await page.goto("/login");
  await tid(page, "dev-user").selectOption("pm@example.com");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("heading", { name: "Tổng quan" })).toBeVisible();
  await page.getByRole("link", { name: "Dịch trực tiếp" }).first().click();
  await tid(page, "live-project").selectOption({ label: (await tid(page, "live-project").locator("option", { hasText: /ALPHA/ }).first().textContent()) ?? "" });
  await tid(page, "live-start-now").click();
  await expect(page).toHaveURL(/\/live$/);

  // Stubs: the user has a Soniox key; the server reports a Soniox interpret session and issues a temporary key.
  await page.route(/\/api\/v1\/meetings\/[^/]+\/audio-sessions$/, async (route) => {
    sessionBodies.push(JSON.parse(route.request().postData() ?? "{}"));
    // The dev server has no Soniox key: create the session as OpenAI/MOCK, then report it as Soniox.
    const sent = JSON.parse(route.request().postData() ?? "{}");
    const res = await route.fetch({ postData: JSON.stringify({ ...sent, stt_provider: "openai" }) });
    const body = await res.json();
    body.session.capture_config = { ...body.session.capture_config, mode: "interpret", stt_provider: "soniox" };
    body.session.is_demo = false;
    await route.fulfill({ response: res, json: body });
  });
  const sessionConfig = {
    model: "stt-rt-v5",
    audio_format: "pcm_s16le",
    sample_rate: 16000,
    num_channels: 1,
    enable_endpoint_detection: true,
    translation: { type: "one_way", target_language: "vi" },
  };
  await page.route(/realtime-token$/, (route) =>
    route.fulfill({
      json: {
        client_secret: "snx_temp_fake",
        expires_at: 0,
        model: "stt-rt-v5",
        kind: "soniox",
        target_language: "vi",
        calls_url: "wss://stt-rt.soniox.com/transcribe-websocket",
        session_config: sessionConfig,
      },
    }),
  );
  await page.route(/\/segments$/, async (route) => {
    segments.push(JSON.parse(route.request().postData() ?? "{}"));
    await route.fulfill({ json: { entries: [], duplicate: false, note: null } });
  });
  await tid(page, "unlock-mics").click();
  await tid(page, "mic-list").getByRole("checkbox").first().check();
  await tid(page, "audio-consent").check();
  await tid(page, "advanced-toggle").click();
  await tid(page, "stt-provider").getByRole("radio", { name: /Soniox/ }).click();
  await expect(tid(page, "caption-latency").getByRole("radio", { name: /Phiên dịch trực tiếp/ })).toHaveAttribute("aria-checked", "true");
  // Soniox honours language hints, so the language choice stays available in interpret mode.
  await expect(tid(page, "language-detection")).toBeVisible();
  await tid(page, "start-audio").click();

  await expect(tid(page, "interim-captions")).toContainText("Hãy xác", { timeout: 20_000 });
  await expect(tid(page, "interim-original")).toContainText("前提");
  await expect.poll(() => segments.length, { timeout: 20_000 }).toBe(1);
  expect(sessionBodies[0]).toMatchObject({ mode: "interpret", stt_provider: "soniox" });
  // First message = server-built config + the temporary key (never the user's own key).
  expect(wsLog.config).toMatchObject({ ...sessionConfig, api_key: "snx_temp_fake" });
  expect(segments[0]).toMatchObject({ text: "前提を確認しましょう。", translated_text: "Hãy xác nhận giả định.", speaker: "1" });
  expect(String(segments[0].item_id)).toMatch(/^sx-/);
  await expect(tid(page, "interim-captions")).toHaveCount(0);

  await tid(page, "stop-audio").click();
  await expect(tid(page, "start-audio")).toBeVisible({ timeout: 30_000 });
  expect(wsLog.ended).toBe(true); // end-of-audio sent so Soniox could finalize
});
