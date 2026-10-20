"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert, Card, EmptyState, Field, Input, PageHeader, Spinner, Stat, Table } from "@/components/ui";
import { ProjectFilter } from "@/components/shared/project-select";
import { errorMessage, formatUsd } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { UsageSummary } from "@/lib/types";

function Bar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-1.5 w-full rounded-full bg-surface-2">
      <div className="h-full rounded bg-brand-500" style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function UsagePage() {
  const [projectId, setProjectId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const { data, error, loading } = useApi<UsageSummary>("/usage/summary", {
    project_id: projectId,
    date_from: from ? `${from}T00:00:00Z` : undefined,
    date_to: to ? `${to}T23:59:59Z` : undefined,
  });
  const maxCost = (rows: { estimated_cost_usd: string }[]) => Math.max(0, ...rows.map((r) => Number(r.estimated_cost_usd)));
  const opLabel = (op: string) => (t.usage.operations as Record<string, string>)[op] ?? op;

  return (
    <>
      <PageHeader title={t.usage.title} />
      <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-3">
        <Field label={t.meetingForm.project}>{(id) => <ProjectFilter id={id} value={projectId} onChange={setProjectId} />}</Field>
        <Field label={t.common.from}>{(id) => <Input id={id} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
        <Field label={t.common.to}>{(id) => <Input id={id} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
      </div>
      {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      {loading && !data && <Spinner />}
      {data && (
        <div className="space-y-4">
          <Alert tone="info">
            {t.usage.byokNote} {data.cost_note}
          </Alert>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label={t.usage.totalRequests} value={data.total_requests} />
            <Stat label={t.usage.estimatedCost} value={formatUsd(data.estimated_cost_usd)} />
            <Stat label={t.usage.failed} value={data.failed_requests} tone={data.failed_requests ? "danger" : undefined} />
            <Stat label={t.usage.tokens} value={`${data.input_tokens.toLocaleString()} / ${data.output_tokens.toLocaleString()}`} hint={`${data.requests_with_estimated_tokens} ${t.usage.estimatedTokens}`} />
            <Stat label={t.usage.processing} value={`${(data.processing_ms / 1000).toFixed(1)} s`} />
          </div>
          {data.total_requests === 0 ? (
            <EmptyState title={t.usage.empty} />
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              <Card title={t.usage.byModel} bodyClassName="p-0">
                <Table>
                  <thead>
                    <tr>
                      <th>{t.settings.model}</th>
                      <th className="text-right">{t.usage.requests}</th>
                      <th className="w-1/3">{t.usage.cost}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_model.map((r) => (
                      <tr key={`${r.provider}/${r.model}`}>
                        <td className="font-mono text-xs">
                          {r.provider}/{r.model}
                        </td>
                        <td className="text-right tabular-nums">{r.requests}</td>
                        <td>
                          <div className="text-xs tabular-nums">{formatUsd(r.estimated_cost_usd)}</div>
                          <Bar value={Number(r.estimated_cost_usd)} max={maxCost(data.by_model)} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>
              <Card title={t.usage.byOperation} bodyClassName="p-0">
                <Table>
                  <thead>
                    <tr>
                      <th />
                      <th className="text-right">{t.usage.requests}</th>
                      <th className="text-right">{t.usage.failed}</th>
                      <th className="text-right">{t.usage.cost}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_operation.map((r) => (
                      <tr key={r.operation}>
                        <td>{opLabel(r.operation)}</td>
                        <td className="text-right tabular-nums">{r.requests}</td>
                        <td className="text-right tabular-nums">{r.failed}</td>
                        <td className="text-right tabular-nums">{formatUsd(r.estimated_cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>
              <Card title={t.usage.byProject} bodyClassName="p-0">
                <Table>
                  <tbody>
                    {data.by_project.map((r) => (
                      <tr key={r.project_id}>
                        <td>{r.project_name}</td>
                        <td className="text-right tabular-nums">{r.requests}</td>
                        <td className="w-1/3">
                          <div className="text-xs tabular-nums">{formatUsd(r.estimated_cost_usd)}</div>
                          <Bar value={Number(r.estimated_cost_usd)} max={maxCost(data.by_project)} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>
              <Card title={t.usage.byMeeting} bodyClassName="p-0">
                <Table>
                  <tbody>
                    {data.by_meeting.map((r) => (
                      <tr key={r.meeting_id}>
                        <td>
                          <Link href={`/meetings/${r.meeting_id}`} className="text-info hover:underline">
                            {r.meeting_title}
                          </Link>
                        </td>
                        <td className="text-right tabular-nums">{r.requests}</td>
                        <td className="text-right tabular-nums">{formatUsd(r.estimated_cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>
            </div>
          )}
        </div>
      )}
    </>
  );
}
