"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert, Button, Card, EmptyState, Field, Input, PageHeader, Select, Spinner, Stat, Table } from "@/components/ui";
import { MemoStatusBadge, MeetingStatusBadge, PriorityBadge } from "@/components/shared/status";
import { ProjectFilter } from "@/components/shared/project-select";
import { errorMessage, formatDateTime, formatUsd } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { Dashboard, MeetingStatus, MemoStatus } from "@/lib/types";

function daysAgoIso(days: number): string {
  return new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
}

export default function DashboardPage() {
  const [projectId, setProjectId] = useState("");
  const [from, setFrom] = useState(daysAgoIso(90));
  const [to, setTo] = useState("");
  const [meetingStatus, setMeetingStatus] = useState<MeetingStatus | "">("");
  const [memoStatus, setMemoStatus] = useState<MemoStatus | "">("");
  const [owner, setOwner] = useState("");
  const { data, error, loading } = useApi<Dashboard>("/dashboard", {
    project_id: projectId,
    date_from: from ? `${from}T00:00:00Z` : undefined,
    date_to: to ? `${to}T23:59:59Z` : undefined,
    meeting_status: meetingStatus,
    memo_status: memoStatus,
    owner,
  });

  return (
    <>
      <PageHeader
        title={t.dashboard.title}
        actions={
          <Link href="/meetings/new">
            <Button variant="primary">{t.nav.newMeeting}</Button>
          </Link>
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-3 rounded-lg border border-line bg-white p-3 md:grid-cols-6">
        <Field label={t.meetingForm.project}>{(id) => <ProjectFilter id={id} value={projectId} onChange={setProjectId} />}</Field>
        <Field label={t.common.from}>{(id) => <Input id={id} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
        <Field label={t.common.to}>{(id) => <Input id={id} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
        <Field label={t.history.columns.status}>
          {(id) => (
            <Select id={id} value={meetingStatus} onChange={(e) => setMeetingStatus(e.target.value as MeetingStatus | "")}>
              <option value="">{t.common.all}</option>
              {Object.entries(t.meetingStatus).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t.history.columns.memo}>
          {(id) => (
            <Select id={id} value={memoStatus} onChange={(e) => setMemoStatus(e.target.value as MemoStatus | "")}>
              <option value="">{t.common.all}</option>
              {(["draft", "in_review", "approved", "rejected", "failed"] as const).map((k) => (
                <option key={k} value={k}>
                  {t.memoStatus[k]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t.dashboard.owner}>{(id) => <Input id={id} value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="…" />}</Field>
      </div>

      {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      {loading && !data && <Spinner label={t.common.loading} />}
      {data && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" data-testid="dashboard-stats">
            <Stat label={t.dashboard.totalMeetings} value={data.total_meetings} />
            <Stat label={t.dashboard.draftsAwaiting} value={data.drafts_awaiting_review} tone={data.drafts_awaiting_review ? "warning" : undefined} />
            <Stat label={t.dashboard.openActions} value={data.open_action_items} hint={`${data.unconfirmed_action_items} ${t.dashboard.unconfirmed.toLowerCase()}`} />
            <Stat label={t.dashboard.overdueActions} value={data.overdue_action_items} tone={data.overdue_action_items ? "danger" : undefined} />
            <Stat label={t.dashboard.highIssues} value={data.high_priority_issues.length + data.high_priority_risks.length} />
            <Stat label={t.dashboard.aiCost} value={formatUsd(data.usage.estimated_cost_usd)} hint={`${data.usage.total_requests} ${t.dashboard.aiRequests}`} />
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card title={t.dashboard.recentMeetings} className="xl:col-span-2" bodyClassName="p-0">
              {data.recent_meetings.length === 0 ? (
                <div className="p-4">
                  <EmptyState
                    title={t.dashboard.emptyMeetings}
                    action={
                      <Link href="/meetings/new">
                        <Button size="sm">{t.dashboard.createFirst}</Button>
                      </Link>
                    }
                  />
                </div>
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <th>{t.history.columns.title}</th>
                      <th>{t.history.columns.project}</th>
                      <th>{t.history.columns.date}</th>
                      <th>{t.history.columns.status}</th>
                      <th>{t.history.columns.memo}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_meetings.map((m) => (
                      <tr key={m.id}>
                        <td>
                          <Link className="text-brand-700 hover:underline" href={`/meetings/${m.id}`}>
                            {m.title}
                          </Link>
                        </td>
                        <td className="text-muted">{m.project_name}</td>
                        <td className="whitespace-nowrap text-muted">{formatDateTime(m.scheduled_at)}</td>
                        <td>
                          <MeetingStatusBadge status={m.status} />
                        </td>
                        <td>
                          <MemoStatusBadge status={m.memo_status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card>

            <Card title={`${t.dashboard.highIssues} / ${t.dashboard.highRisks}`}>
              {data.high_priority_issues.length + data.high_priority_risks.length === 0 ? (
                <p className="text-sm text-muted">{t.dashboard.emptyIssues}</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {data.high_priority_issues.map((i) => (
                    <li key={i.id} className="flex gap-2">
                      <PriorityBadge priority={i.priority} />
                      <Link href={`/meetings/${i.meeting_id}/memo`} className="hover:underline">
                        <span className="font-mono text-xs text-muted">{i.code}</span> {i.description}
                        <span className="block text-xs text-muted">{i.meeting_title}</span>
                      </Link>
                    </li>
                  ))}
                  {data.high_priority_risks.map((r) => (
                    <li key={r.id} className="flex gap-2">
                      <PriorityBadge priority={r.severity} />
                      <Link href={`/meetings/${r.meeting_id}/memo`} className="hover:underline">
                        <span className="font-mono text-xs text-muted">{r.code}</span> {r.description}
                        <span className="block text-xs text-muted">{r.meeting_title}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card title={t.dashboard.activity} bodyClassName="p-0">
            {data.recent_activity.length === 0 ? (
              <p className="p-4 text-sm text-muted">{t.dashboard.emptyActivity}</p>
            ) : (
              <Table>
                <tbody>
                  {data.recent_activity.map((a, i) => (
                    <tr key={i}>
                      <td className="w-40 whitespace-nowrap text-xs text-muted">{formatDateTime(a.created_at)}</td>
                      <td className="text-xs">{a.actor ?? t.common.none}</td>
                      <td className="font-mono text-xs">{a.action}</td>
                      <td className="text-xs text-muted">{a.project_name}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
