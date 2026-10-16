"use client";

import { Badge, Spinner, Table } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { IntegrationDiagnostics as Diag, PlatformProvider } from "@/lib/types";

/** Safe diagnostics: timestamps and error categories only — never tokens or secrets. */
export function IntegrationDiagnostics({ provider }: { provider: PlatformProvider }) {
  const { data } = useApi<Diag>(`/integrations/${provider}/diagnostics`);
  if (!data) return <Spinner />;
  const c = data.connection;
  return (
    <div className="space-y-3 text-sm" data-testid={`diagnostics-${provider}`}>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-muted">{t.integrations.lastAttempt}</dt>
        <dd>{formatDateTime(c.last_attempt_at)}</dd>
        <dt className="text-muted">{t.integrations.lastSuccess}</dt>
        <dd>{formatDateTime(c.last_success_at)}</dd>
        <dt className="text-muted">{t.integrations.lastEvent}</dt>
        <dd>{formatDateTime(c.last_event_at)}</dd>
        <dt className="text-muted">{t.integrations.reconnects}</dt>
        <dd>{c.reconnect_count}</dd>
        <dt className="text-muted">{t.integrations.category}</dt>
        <dd className="font-mono">{c.last_error_category ?? t.common.none}</dd>
      </dl>
      <div>
        <p className="mb-1 text-xs font-medium">{t.integrations.jobs}</p>
        {data.recent_jobs.length === 0 ? (
          <p className="text-xs text-muted">{t.integrations.noEvents}</p>
        ) : (
          <Table>
            <tbody>
              {data.recent_jobs.map((j) => (
                <tr key={j.id}>
                  <td className="text-xs whitespace-nowrap text-muted">{formatDateTime(j.created_at)}</td>
                  <td className="font-mono text-xs">{j.kind}</td>
                  <td>
                    <Badge tone={j.status === "failed" ? "danger" : j.status === "succeeded" ? "success" : "info"}>{t.jobStatus[j.status]}</Badge>
                  </td>
                  <td className="font-mono text-xs">{j.error_code ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
      <div>
        <p className="mb-1 text-xs font-medium">{t.integrations.events}</p>
        {data.recent_events.length === 0 ? (
          <p className="text-xs text-muted">{t.integrations.noEvents}</p>
        ) : (
          <Table>
            <tbody>
              {data.recent_events.map((e, i) => (
                <tr key={i}>
                  <td className="text-xs whitespace-nowrap text-muted">{formatDateTime(e.received_at)}</td>
                  <td className="font-mono text-xs">{e.event_type}</td>
                  <td>
                    <Badge>{e.status}</Badge>
                  </td>
                  <td className="text-xs text-muted">{e.detail}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
    </div>
  );
}
