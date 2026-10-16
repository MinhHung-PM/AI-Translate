"use client";

import { useState } from "react";
import { Alert, Button, Dialog } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { ConnectionView } from "@/lib/types";
import { PermissionStatus } from "./PermissionStatus";

/**
 * Guided connection: prerequisites → server-side OAuth (state + PKCE) → back on
 * /integrations the result and the verified capabilities are shown.
 * Tokens never reach the browser; only the provider's authorization URL does.
 */
export function ConnectionWizard({ view, open, onClose }: { view: ConnectionView; open: boolean; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const unsupported = view.capabilities.filter((c) => c.status !== "available");

  async function startAuth() {
    setBusy(true);
    setError(null);
    try {
      const { authorization_url } = await api.post<{ authorization_url: string }>(`/integrations/${view.provider}/connect`);
      window.location.assign(authorization_url);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={`${t.integrations.wizard.title}: ${view.display_name}`} wide>
      <ol className="space-y-4 text-sm" data-testid="connection-wizard">
        <li>
          <p className="font-medium">{t.integrations.wizard.step1}</p>
          <p className="text-muted">{view.display_name}</p>
        </li>
        <li>
          <p className="font-medium">{t.integrations.wizard.step2}</p>
          {view.configured ? (
            <Alert tone="success">{t.integrations.wizard.prereqOk}</Alert>
          ) : (
            <Alert tone="warning" title={t.integrations.wizard.prereqMissing}>
              <ul className="ml-4 list-disc font-mono text-xs">
                {view.configuration_problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </Alert>
          )}
          {view.redirect_uri && (
            <p className="mt-1 text-xs text-muted">
              {t.integrations.redirectUri}: <code className="break-all">{view.redirect_uri}</code>
            </p>
          )}
          {view.requested_scopes.length > 0 && (
            <p className="mt-1 text-xs text-muted">
              {t.integrations.scopes}: <code className="break-all">{view.requested_scopes.join(" ")}</code>
            </p>
          )}
          {view.sandbox && <Alert tone="danger" className="mt-2">{t.integrations.sandbox}</Alert>}
        </li>
        <li>
          <p className="font-medium">{t.integrations.wizard.step3}</p>
          <p className="mb-2 text-xs text-muted">{t.integrations.wizard.authNote}</p>
          <Button variant="primary" onClick={() => void startAuth()} loading={busy} disabled={!view.configured} data-testid="wizard-authorize">
            {t.integrations.wizard.startAuth}
          </Button>
          {error && <Alert tone="danger" className="mt-2">{error}</Alert>}
        </li>
        <li>
          <p className="font-medium">{t.integrations.wizard.step4}</p>
          <p className="mb-1 text-xs text-muted">{t.integrations.wizard.unsupported}</p>
          <PermissionStatus capabilities={unsupported} />
        </li>
      </ol>
    </Dialog>
  );
}
