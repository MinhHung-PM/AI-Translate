"use client";

import { useState } from "react";
import { Alert, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { ConnectionView } from "@/lib/types";
import { ConnectionWizard } from "./ConnectionWizard";
import { IntegrationDiagnostics } from "./IntegrationDiagnostics";
import { ConnectionStatusBadge, PermissionStatus, SandboxBadge } from "./PermissionStatus";

export function PlatformConnectionCard({ view, onChanged }: { view: ConnectionView; onChanged: (v: ConnectionView) => void }) {
  const [wizard, setWizard] = useState(false);
  const [diag, setDiag] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const connected = ["connected", "connected_post_meeting_only", "temporarily_disconnected", "admin_approval_required", "error"].includes(view.status) && view.account;

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setMessage(null);
    try {
      await fn();
    } catch (err) {
      setMessage({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          {view.display_name} <ConnectionStatusBadge status={view.status} /> {view.sandbox && <SandboxBadge />}
        </span>
      }
      className="flex flex-col"
    >
      <div className="space-y-3" data-testid={`platform-${view.provider}`} data-status={view.status}>
        {view.sandbox && <Alert tone="danger">{t.integrations.sandbox}</Alert>}
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted">{t.integrations.account}</dt>
          <dd className="truncate" title={view.account ?? undefined}>
            {view.account ?? t.common.none}
          </dd>
          <dt className="text-muted">{t.integrations.lastSuccess}</dt>
          <dd>{formatDateTime(view.last_success_at)}</dd>
        </dl>
        {view.last_error_message && view.status !== "connected" && view.status !== "connected_post_meeting_only" && (
          <Alert tone={view.status === "admin_approval_required" ? "warning" : "danger"} title={t.integrations.lastError}>
            {view.last_error_message}
          </Alert>
        )}
        {!view.configured && (
          <Alert tone="neutral" title={t.integrations.missingConfig}>
            <span className="font-mono text-xs">{view.configuration_problems.join(", ")}</span>
          </Alert>
        )}
        <PermissionStatus capabilities={view.capabilities} />
        {message && <Alert tone={message.tone}>{message.text}</Alert>}
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" size="sm" onClick={() => setWizard(true)} data-testid={`connect-${view.provider}`}>
            {connected ? t.integrations.reconnect : t.integrations.connect}
          </Button>
          {connected && (
            <Button
              size="sm"
              loading={busy === "test"}
              onClick={() =>
                void run("test", async () => {
                  const r = await api.post<{ ok: boolean; message: string; connection: ConnectionView }>(`/integrations/${view.provider}/test`);
                  onChanged(r.connection);
                  setMessage({ tone: r.ok ? "success" : "danger", text: r.message });
                })
              }
            >
              {t.integrations.test}
            </Button>
          )}
          {connected && (
            <Button
              size="sm"
              variant="danger"
              loading={busy === "disconnect"}
              onClick={() => {
                if (!window.confirm(t.integrations.disconnectConfirm)) return;
                void run("disconnect", async () => onChanged(await api.del<ConnectionView>(`/integrations/${view.provider}`)));
              }}
            >
              {t.integrations.disconnect}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setDiag((d) => !d)}>
            {t.integrations.diagnostics}
          </Button>
        </div>
        {diag && <IntegrationDiagnostics provider={view.provider} />}
      </div>
      <ConnectionWizard view={view} open={wizard} onClose={() => setWizard(false)} />
    </Card>
  );
}
