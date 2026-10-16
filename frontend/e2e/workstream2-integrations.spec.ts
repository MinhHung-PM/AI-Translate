import { expect, test, type Page } from "@playwright/test";

// Workstream 2 E2E against the FAKE provider server (backend/tests/fakes/server.py,
// DEV/TEST ONLY). Every connection made here is labelled SANDBOX; nothing in this
// test talks to a real Microsoft, Zoom or Google endpoint.
const FAKE = process.env.E2E_FAKE_PROVIDERS_URL ?? "http://127.0.0.1:9100";
const tid = (page: Page, id: string) =>
  page.getByTestId(id).filter({ visible: true });

async function login(page: Page, email: string) {
  await page.goto("/login");
  await tid(page, "dev-user").selectOption(email);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("heading", { name: "Tổng quan" })).toBeVisible();
}

async function scenario(page: Page, provider: string, name: string) {
  const r = await page.request.post(
    `${FAKE}/__scenario?provider=${provider}&name=${name}`,
  );
  expect(r.ok()).toBeTruthy();
}

async function connect(page: Page, provider: string) {
  await page.goto("/integrations");
  await tid(page, `connect-${provider}`).click();
  await expect(tid(page, "connection-wizard")).toBeVisible();
  await tid(page, "wizard-authorize").click();
  // Browser goes to the (fake) provider's authorize URL, which redirects back to our callback.
  await expect(page).toHaveURL(
    new RegExp(`/integrations\\?provider=${provider}&result=`),
  );
}

async function disconnectIfConnected(page: Page, provider: string) {
  await page.goto("/integrations");
  const card = tid(page, `platform-${provider}`);
  await expect(card).toBeVisible();
  const btn = card.getByRole("button", { name: "Ngắt kết nối" });
  if (await btn.count()) {
    page.once("dialog", (d) => void d.accept());
    await btn.click();
    await expect(card).toHaveAttribute("data-status", "not_connected");
  }
}

test("Sandbox platform connection → link Zoom meeting → fetch transcript → translate → memo", async ({
  page,
}) => {
  await login(page, "member@example.com");
  await scenario(page, "zoom", "");
  await disconnectIfConnected(page, "zoom");

  // Truthful card before connecting: SANDBOX label, not connected, Teams live never offered.
  await page.goto("/integrations");
  await expect(tid(page, "platform-zoom")).toHaveAttribute(
    "data-status",
    "not_connected",
  );
  await expect(
    page.getByText(/SANDBOX — endpoint giả lập/).first(),
  ).toBeVisible();
  await expect(
    tid(page, "platform-teams").locator('[data-capability="live_transcript"]'),
  ).toHaveAttribute("data-status", "not_supported");
  await expect(
    tid(page, "platform-google_meet").locator(
      '[data-capability="live_transcript"]',
    ),
  ).toHaveAttribute("data-status", "not_supported");

  await connect(page, "zoom");
  await expect(page.getByText("Kết nối thành công.")).toBeVisible();
  await expect(tid(page, "platform-zoom")).toHaveAttribute(
    "data-status",
    /^connected/,
  );
  await expect(
    tid(page, "platform-zoom").locator(
      '[data-capability="post_meeting_transcript"]',
    ),
  ).toHaveAttribute("data-status", "available");
  // The browser never sees platform tokens.
  const body = await page.content();
  expect(body).not.toMatch(/zoom-(at|rt)-[0-9a-f]{12}/);

  // New meeting in the seeded ALPHA project, platform = Zoom.
  await page.getByRole("link", { name: "Cuộc họp mới" }).first().click();
  const title = `Zoom sync E2E ${Date.now().toString().slice(-6)}`;
  await page
    .getByLabel("Tiêu đề cuộc họp")
    .filter({ visible: true })
    .fill(title);
  const projectSelect = page.locator('select[name="project_id"]');
  await projectSelect.selectOption(
    (await projectSelect
      .locator("option", { hasText: /ALPHA/ })
      .first()
      .getAttribute("value")) ?? "",
  );
  await page
    .getByLabel("Nền tảng họp")
    .filter({ visible: true })
    .selectOption("zoom");
  await page.getByRole("button", { name: "Tạo cuộc họp" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("Zoom · Chưa liên kết cuộc họp")).toBeVisible();

  // Link the platform meeting and fetch the authorized post-meeting transcript.
  const meetingUrl = page.url();
  try {
    await expect(tid(page, "source-provider")).toHaveValue("zoom");
    await tid(page, "source-reference").fill(
      "https://us02web.zoom.us/j/85746065432?pwd=abc",
    );
    await tid(page, "source-link").click();
    await expect(tid(page, "meeting-source")).toContainText("85746065432");
    await expect(tid(page, "meeting-source")).toContainText("SANDBOX");
    await tid(page, "source-fetch").click();
    await expect(tid(page, "meeting-source")).toHaveAttribute(
      "data-transcript-status",
      "imported",
    );
    await expect(tid(page, "transcript-table")).toContainText("Sarah Johnson");
    await expect(tid(page, "transcript-table")).toContainText("release plan");

    // Translation (mock AI provider) and memo generation reuse the Workstream 1 pipeline.
    await tid(page, "translate-all").click();
    await expect(tid(page, "transcript-table")).toContainText("[MOCK");
    await tid(page, "generate-memo").click();
    await expect(page).toHaveURL(/\/memo$/);
    await expect(page.getByText("AI không thể tự phê duyệt")).toBeVisible();
  } finally {
    // A platform meeting can be linked to only one hub meeting: unlink so the test is re-runnable.
    await page.goto(meetingUrl);
    const unlink = tid(page, "meeting-source").getByRole("button", {
      name: "Hủy liên kết",
    });
    await expect(unlink.or(tid(page, "source-reference"))).toBeVisible();
    if (await unlink.count()) {
      await unlink.click();
      await expect(tid(page, "source-reference")).toBeVisible();
    }
  }

  await disconnectIfConnected(page, "zoom");
});

test("Teams admin-consent requirement is shown truthfully, never as connected", async ({
  page,
}) => {
  await login(page, "member@example.com");
  await scenario(page, "teams", "consent_denied_admin");
  try {
    await connect(page, "teams");
    await expect(page).toHaveURL(
      /result=error&category=admin_approval_required/,
    );
    await expect(tid(page, "platform-teams")).toHaveAttribute(
      "data-status",
      "admin_approval_required",
    );
    await expect(
      page.getByText("Kết nối không thành công").first(),
    ).toBeVisible();
  } finally {
    await scenario(page, "teams", "");
  }
});
