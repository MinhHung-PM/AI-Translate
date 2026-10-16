import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const SAMPLES = path.resolve(__dirname, "../../samples");

// Next.js 16 (cacheComponents) keeps recently visited routes mounted but hidden
// via <Activity>, so locators are scoped to visible elements.
const tid = (page: Page, id: string) => page.getByTestId(id).filter({ visible: true });

async function login(page: Page, email: string) {
  await page.goto("/login");
  await tid(page, "dev-user").selectOption(email);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("heading", { name: "Tổng quan" })).toBeVisible();
}

async function createMeeting(page: Page, projectLabel: RegExp, title: string) {
  await page.getByRole("link", { name: "Cuộc họp mới" }).first().click();
  await page.getByLabel("Tiêu đề cuộc họp").filter({ visible: true }).fill(title);
  const projectSelect = page.locator('select[name="project_id"]');
  const option = projectSelect.locator("option", { hasText: projectLabel });
  await projectSelect.selectOption(await option.first().getAttribute("value") ?? "");
  await page.getByLabel("Thành phần tham dự").filter({ visible: true }).fill("田中 | Sakura Logistics\nNguyen An | Dev\n佐藤");
  await page.getByRole("button", { name: "Tạo cuộc họp" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
}

test("Create project → meeting → import → translate → memo → review → approve → confirm → export", async ({ page }) => {
  const code = `E2E${Date.now().toString().slice(-6)}`;
  await login(page, "pm@example.com");

  // Create project
  await page.getByRole("link", { name: "Dự án" }).first().click();
  await tid(page, "create-project").click();
  await tid(page, "project-code").fill(code);
  await tid(page, "project-name").fill(`Dự án kiểm thử ${code}`);
  await tid(page, "project-submit").click();
  await expect(page.getByRole("link", { name: `Dự án kiểm thử ${code}` })).toBeVisible();

  // Create meeting (Teams platform shows "not configured", never "connected")
  await page.getByRole("link", { name: "Cuộc họp mới" }).first().click();
  await page.getByLabel("Nền tảng họp").filter({ visible: true }).selectOption("teams");
  await expect(page.getByText("Chưa cấu hình tích hợp").first()).toBeVisible();
  await page.getByLabel("Nền tảng họp").filter({ visible: true }).selectOption("manual_import");
  await createMeeting(page, new RegExp(code), "Họp định nghĩa yêu cầu E2E");

  // Import transcript (VTT)
  await tid(page, "transcript-file").setInputFiles(path.join(SAMPLES, "ja_client_meeting.vtt"));
  await tid(page, "import-submit").click();
  await expect(tid(page, "transcript-row")).toHaveCount(8);
  await expect(tid(page, "transcript-table")).toContainText("在庫引当機能");

  // Translate full transcript (async job) — translations appear beside originals
  await tid(page, "translate-all").click();
  await expect(tid(page, "translation-stats")).toContainText("Đã dịch: 8");
  await expect(tid(page, "transcript-table")).toContainText("[MOCK ja→vi]");

  // Generate memo
  await tid(page, "generate-memo").click();
  await expect(page).toHaveURL(/\/memo$/);
  await expect(tid(page, "items-decisions").getByTestId("memo-item").first()).toBeVisible();
  await expect(page.getByText("AI không thể tự phê duyệt")).toBeVisible();

  // Edit the executive summary and save the draft
  const summary = tid(page, "summary-editor").locator("textarea");
  await summary.fill("Thống nhất màn hình chỉ thị xuất hàng dạng tab; cập nhật thiết kế trước thứ Sáu tuần sau.");
  await tid(page, "save-draft").click();
  await expect(tid(page, "save-draft")).toBeDisabled();

  // Source reference links back to the transcript
  const firstRef = tid(page, "items-decisions").getByRole("link", { name: /#\d+/ }).first();
  await expect(firstRef).toHaveAttribute("href", /\?entry=/);

  // Submit for review and approve (human approval)
  await tid(page, "submit-memo").click();
  await expect(page.getByText("Chờ duyệt").first()).toBeVisible();
  await tid(page, "approve-memo").click();
  await tid(page, "confirm-review").click();
  await expect(page.getByText("Đã duyệt").first()).toBeVisible();

  // Confirm an AI-extracted action item (allowed after approval)
  const actions = tid(page, "items-action-items");
  const beforeConfirmed = await actions.getByText("Đã xác nhận").count();
  await actions.getByTestId("confirm-item").first().click();
  await expect(actions.getByText("Đã xác nhận")).toHaveCount(beforeConfirmed + 1);

  // Export approved memo (Markdown)
  const downloadPromise = page.waitForEvent("download");
  await tid(page, "export-md").click();
  const download = await downloadPromise;
  const content = readFileSync((await download.path())!, "utf8");
  expect(content).toContain("Họp định nghĩa yêu cầu E2E");
  expect(content).toContain("Thống nhất màn hình chỉ thị xuất hàng dạng tab");
  expect(content).toContain("## E.");

  // Action tracker lists the meeting's actions
  await page.getByRole("link", { name: "Theo dõi công việc" }).first().click();
  await expect(tid(page, "action-rows")).toContainText("Họp định nghĩa yêu cầu E2E");

  // History search finds the meeting with approved memo
  await page.getByRole("link", { name: "Lịch sử cuộc họp" }).first().click();
  await page.getByLabel("Tìm kiếm").filter({ visible: true }).fill("định nghĩa yêu cầu E2E");
  await expect(tid(page, "history-rows")).toContainText("Đã duyệt");
});

test("Replay demo is clearly labelled and streams translated entries", async ({ page }) => {
  await login(page, "pm@example.com");
  await createMeeting(page, /ALPHA/, `Replay demo ${Date.now()}`);
  await page.getByRole("link", { name: "Trực tiếp / Phát lại" }).click();
  await page.getByRole("tab", { name: "Phát lại (Demo)" }).filter({ visible: true }).click();
  await expect(tid(page, "demo-banner")).toContainText("KHÔNG phải kết nối cuộc họp thực");
  await page.getByLabel("Khoảng cách giữa các đoạn (giây)").filter({ visible: true }).fill("0.3");
  await page.getByLabel("Hoặc dán văn bản").filter({ visible: true }).fill("田中: 本日の議題を確認します。\nNguyen: 仕様書を共有します。\n田中: 了解しました。");
  await tid(page, "start-replay").click();
  await expect(tid(page, "replay-status")).toHaveText("completed", { timeout: 30_000 });
  await expect(tid(page, "transcript-row")).toHaveCount(3);
  await expect(tid(page, "transcript-table")).toContainText("[MOCK ja→vi]");
  await expect(tid(page, "transcript-table")).toContainText("DEMO");
});

test("Unauthorized users cannot reach another project's meeting", async ({ page, browser }) => {
  await login(page, "pm@example.com");
  await createMeeting(page, /ALPHA/, `Private meeting ${Date.now()}`);
  const url = page.url();
  const other = await browser.newPage();
  await login(other, "outsider@example.com");
  await other.goto(url);
  await expect(other.getByText(/không có quyền truy cập|Meeting not found/)).toBeVisible();
  await other.close();
});
