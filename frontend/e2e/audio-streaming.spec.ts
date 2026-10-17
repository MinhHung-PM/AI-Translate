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
        dc.onopen = async () => {
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
  await expect(tid(page, "audio-streaming")).toBeChecked();
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
