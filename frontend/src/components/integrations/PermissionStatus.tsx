import { Badge } from "@/components/ui";
import { t } from "@/lib/i18n";
import type { CapabilityState, CapabilityStatusName, ConnectionDisplayStatus } from "@/lib/types";

const CAP_TONE: Record<CapabilityStatusName, "success" | "warning" | "neutral" | "danger" | "info"> = {
  available: "success",
  requires_configuration: "neutral",
  requires_user_consent: "info",
  requires_admin_approval: "warning",
  not_supported: "neutral",
  temporarily_unavailable: "danger",
};

const STATUS_TONE: Record<ConnectionDisplayStatus, "success" | "warning" | "neutral" | "danger" | "info"> = {
  not_configured: "neutral",
  not_connected: "neutral",
  awaiting_authorization: "info",
  connected: "success",
  connected_post_meeting_only: "success",
  admin_approval_required: "warning",
  temporarily_disconnected: "warning",
  error: "danger",
};

export function ConnectionStatusBadge({ status }: { status: ConnectionDisplayStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{t.integrations.status[status]}</Badge>;
}

export function SandboxBadge() {
  return (
    <Badge tone="danger" title={t.integrations.sandbox}>
      SANDBOX
    </Badge>
  );
}

/** Capability list with truthful statuses, explanations and remediation steps. */
export function PermissionStatus({ capabilities, compact }: { capabilities: CapabilityState[]; compact?: boolean }) {
  return (
    <ul className="divide-y divide-line text-sm" data-testid="capabilities">
      {capabilities.map((c) => (
        <li key={c.capability} className="flex flex-col gap-0.5 py-1.5" data-capability={c.capability} data-status={c.status}>
          <div className="flex items-center justify-between gap-2">
            <span>{t.integrations.capability[c.capability]}</span>
            <Badge tone={CAP_TONE[c.status]}>{t.integrations.capStatus[c.status]}</Badge>
          </div>
          {!compact && <p className="text-xs text-muted">{c.message}</p>}
          {!compact && c.remediation && c.status !== "available" && <p className="text-xs text-amber-800">→ {c.remediation}</p>}
        </li>
      ))}
    </ul>
  );
}
