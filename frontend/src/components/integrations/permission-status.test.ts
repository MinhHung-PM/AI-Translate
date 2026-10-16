import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { t } from "@/lib/i18n";
import type { CapabilityName, CapabilityState, CapabilityStatusName, ConnectionDisplayStatus } from "@/lib/types";
import { ConnectionStatusBadge, PermissionStatus } from "./PermissionStatus";

const CAPS: CapabilityName[] = [
  "transcript_import",
  "list_meetings",
  "post_meeting_transcript",
  "live_transcript",
  "live_audio",
  "speaker_metadata",
  "meeting_event_notifications",
  "recovery_after_disconnect",
];
const STATUSES: CapabilityStatusName[] = ["available", "requires_configuration", "requires_user_consent", "requires_admin_approval", "not_supported", "temporarily_unavailable"];
const DISPLAY: ConnectionDisplayStatus[] = [
  "not_configured",
  "not_connected",
  "awaiting_authorization",
  "connected",
  "connected_post_meeting_only",
  "admin_approval_required",
  "temporarily_disconnected",
  "error",
];

describe("integration status UI", () => {
  it("has a Vietnamese label for every capability, capability status and connection status", () => {
    for (const c of CAPS) expect(t.integrations.capability[c]).toBeTruthy();
    for (const s of STATUSES) expect(t.integrations.capStatus[s]).toBeTruthy();
    for (const d of DISPLAY) expect(renderToStaticMarkup(createElement(ConnectionStatusBadge, { status: d }))).toContain(t.integrations.status[d]);
  });

  it("shows remediation only for capabilities that are not available", () => {
    const caps: CapabilityState[] = [
      { capability: "post_meeting_transcript", status: "available", message: "ok", remediation: "NOT-SHOWN", verified_live: false },
      { capability: "live_transcript", status: "requires_admin_approval", message: "needs admin", remediation: "Ask your tenant admin", verified_live: false },
    ];
    const html = renderToStaticMarkup(createElement(PermissionStatus, { capabilities: caps }));
    expect(html).toContain('data-status="requires_admin_approval"');
    expect(html).toContain("Ask your tenant admin");
    expect(html).not.toContain("NOT-SHOWN");
    expect(html).toContain(t.integrations.capStatus.requires_admin_approval);
  });
});
