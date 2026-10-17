import { expect, test, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Live audio capture through a FAKE microphone (Chromium flag) fed with a
// generated speech-like WAV. The server uses the MOCK speech-to-text because
// no OpenAI key is configured in E2E — the text is labelled [MOCK STT].
const RATE = 16000;
function speechLikeWav(): string {
  const parts: number[] = [];
  const push = (ms: number, amp: number) => {
    const n = (RATE * ms) / 1000;
    for (let i = 0; i < n; i++) parts.push(amp * Math.sin((2 * Math.PI * 220 * i) / RATE));
  };
  push(800, 0.001);
  for (let k = 0; k < 7; k++) {
    push(300, 0.4); // syllable
    push(90, 0.001); // short gap
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
  const file = path.join(tmpdir(), "memohub-fake-mic.wav");
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

test("Capture microphone audio → recognised, speaker-labelled and translated live", async ({ page }) => {
  await page.goto("/login");
  await tid(page, "dev-user").selectOption("pm@example.com");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("heading", { name: "Tổng quan" })).toBeVisible();

  // Entry point: "Dịch trực tiếp" in the main menu → one-click start.
  await page.getByRole("link", { name: "Dịch trực tiếp" }).first().click();
  await expect(tid(page, "live-quick-start")).toBeVisible();
  await tid(page, "live-project").selectOption({ label: (await tid(page, "live-project").locator("option", { hasText: /ALPHA/ }).first().textContent()) ?? "" });
  await tid(page, "live-start-now").click();
  await expect(page).toHaveURL(/\/meetings\/[0-9a-f-]+\/live$/);
  await expect(tid(page, "audio-capture")).toBeVisible();
  await expect(tid(page, "start-audio")).toBeDisabled();

  await tid(page, "unlock-mics").click();
  const firstMic = tid(page, "mic-list").getByRole("checkbox").first();
  await firstMic.check();
  await expect(tid(page, "picked-sources")).toContainText("MIC");
  // Automatic noise suppression is on by default ("Tiêu chuẩn"); the audio below reaches
  // recognition through the filter chain (high-pass → low-pass → adaptive noise gate).
  await expect(tid(page, "noise-level").getByRole("radio", { checked: true })).toContainText("Tiêu chuẩn");
  await tid(page, "audio-consent").check();
  await tid(page, "start-audio").click();
  await expect(tid(page, "audio-sources-live")).toContainText(/đang nghe giọng nói|đang chặn tạp âm/, { timeout: 15_000 });

  await expect(tid(page, "audio-sources-live")).toBeVisible();
  await expect(tid(page, "audio-banner")).toContainText("MOCK");
  // Utterances are detected in the browser, recognised (mock) and translated.
  // Manga speech bubbles: original line, speaker, and translation headline.
  await expect(tid(page, "caption-feed")).toContainText("[MOCK STT]", { timeout: 30_000 });
  await expect(tid(page, "caption-bubble").first()).toContainText("Tôi");
  await expect(tid(page, "caption-bubble").first()).toContainText("[MOCK", { timeout: 30_000 });
  // The bilingual table view is still available.
  await page.getByRole("tab", { name: "Bảng song ngữ" }).click();
  await expect(tid(page, "transcript-table")).toContainText("[MOCK STT]");
  await page.getByRole("tab", { name: "Bong bóng hội thoại" }).click();

  await tid(page, "stop-audio").click();
  await expect(tid(page, "replay-status")).toHaveText("stopped", { timeout: 30_000 });
  await expect(tid(page, "start-audio")).toBeVisible();

  // After the live session: one click to the AI meeting memo.
  await expect(tid(page, "live-finished")).toBeVisible();
  await tid(page, "live-generate-memo").click();
  await expect(page).toHaveURL(/\/memo$/);
  await expect(page.getByText("AI không thể tự phê duyệt")).toBeVisible({ timeout: 30_000 });
});
