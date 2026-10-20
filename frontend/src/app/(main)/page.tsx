"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert, Badge, Button, EmptyState, FilterPill, Fred, Input, Select, Spinner, Stat, pillControl } from "@/components/ui";
import { MemoStatusBadge } from "@/components/shared/status";
import { ProjectFilter } from "@/components/shared/project-select";
import { errorMessage, formatDateTime, formatUsd } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { Dashboard, MeetingStatus, MemoStatus } from "@/lib/types";

function daysAgoIso(days: number): string {
  return new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
}

/** "19.10" — compact day.month for list rows. */
function dayMonth(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;
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
  const highCount = data ? data.high_priority_issues.length + data.high_priority_risks.length : 0;

  return (
    <div className="flex flex-col gap-[22px]">
      <div className="relative flex flex-wrap items-center gap-4 overflow-hidden rounded-[18px] border border-line bg-surface px-[22px] py-[18px]">
        <Fred pose="wave" className="-my-[18px] -ml-1.5 h-[92px] w-auto self-end" priority />
        <div className="flex min-w-60 flex-1 flex-col gap-1">
          <h1 className="eyebrow text-muted">{t.dashboard.title}</h1>
          <p className="font-display text-[clamp(20px,2.2vw,26px)] leading-tight font-semibold">{t.dashboard.greeting}</p>
          {data && (
            <p className="text-sm text-muted">
              {data.drafts_awaiting_review || data.overdue_action_items
                ? t.dashboard.greetingSub.replace("{drafts}", String(data.drafts_awaiting_review)).replace("{overdue}", String(data.overdue_action_items))
                : t.dashboard.greetingClear}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/live">
            <Button variant="primary" data-testid="dashboard-live">
              {t.nav.liveTranslate}
            </Button>
          </Link>
          <Link href="/meetings/new">
            <Button>{t.nav.newMeeting}</Button>
          </Link>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <FilterPill label={t.meetingForm.project}>
          <ProjectFilter value={projectId} onChange={setProjectId} className={`${pillControl} max-w-56`} />
        </FilterPill>
        <FilterPill label={t.common.from}>
          <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={pillControl} aria-label={t.common.from} />
        </FilterPill>
        <FilterPill label={t.common.to}>
          <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={pillControl} aria-label={t.common.to} />
        </FilterPill>
        <FilterPill label={t.history.columns.status}>
          <Select value={meetingStatus} onChange={(e) => setMeetingStatus(e.target.value as MeetingStatus | "")} className={pillControl} aria-label={t.history.columns.status}>
            <option value="">{t.common.all}</option>
            {Object.entries(t.meetingStatus).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </Select>
        </FilterPill>
        <FilterPill label={t.history.columns.memo}>
          <Select value={memoStatus} onChange={(e) => setMemoStatus(e.target.value as MemoStatus | "")} className={pillControl} aria-label={t.history.columns.memo}>
            <option value="">{t.common.all}</option>
            {(["draft", "in_review", "approved", "rejected", "failed"] as const).map((k) => (
              <option key={k} value={k}>
                {t.memoStatus[k]}
              </option>
            ))}
          </Select>
        </FilterPill>
        <FilterPill label={t.dashboard.owner}>
          <Input value={owner} onChange={(e) => setOwner(e.target.value)} placeholder={t.common.all} className={`${pillControl} w-28`} aria-label={t.dashboard.owner} />
        </FilterPill>
      </div>

      {error && <Alert tone="danger" fred="sad">{errorMessage(error)}</Alert>}
      {loading && !data && <Spinner label={t.common.loading} />}
      {data && (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3" data-testid="dashboard-stats">
            <Stat label={t.dashboard.totalMeetings} value={data.total_meetings} />
            <Link href="/meetings?memo=in_review" className="rounded-[14px]">
              <Stat label={t.dashboard.draftsAwaiting} value={data.drafts_awaiting_review} tone="warning" />
            </Link>
            <Link href="/actions" className="rounded-[14px]">
              <Stat label={t.dashboard.openActions} value={data.open_action_items} hint={`${data.unconfirmed_action_items} ${t.dashboard.unconfirmed.toLowerCase()}`} tone="info" />
            </Link>
            <Link href="/actions?overdue=1" className="rounded-[14px]">
              <Stat label={t.dashboard.overdueActions} value={data.overdue_action_items} tone="danger" />
            </Link>
            <Stat label={t.dashboard.highIssues} value={highCount} tone="danger" />
            <Link href="/usage" className="rounded-[14px]">
              <Stat label={t.dashboard.aiCost} value={formatUsd(data.usage.estimated_cost_usd)} hint={`${data.usage.total_requests} ${t.dashboard.aiRequests}`} />
            </Link>
          </div>

          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,380px),1fr))] items-start gap-4">
            <section className="panel flex flex-col gap-1 p-[18px] min-[1280px]:col-span-2">
              <div className="flex items-center justify-between pb-2">
                <h2 className="text-[15px] font-semibold">{t.dashboard.recentMeetings}</h2>
                <Link href="/meetings" className="text-[13px] text-info">
                  {t.dashboard.seeAll}
                </Link>
              </div>
              {data.recent_meetings.length === 0 ? (
                <EmptyState
                  fred="pointing"
                  title={t.dashboard.emptyMeetings}
                  action={
                    <Link href="/meetings/new">
                      <Button size="sm">{t.dashboard.createFirst}</Button>
                    </Link>
                  }
                />
              ) : (
                data.recent_meetings.map((m) => (
                  <Link
                    key={m.id}
                    href={m.memo_status ? `/meetings/${m.id}/memo` : `/meetings/${m.id}`}
                    className="grid grid-cols-[60px_minmax(0,1fr)_auto] items-center gap-3 border-t border-line px-1.5 py-[11px] hover:bg-surface-2/50"
                  >
                    <span className="font-mono text-xs text-muted">{dayMonth(m.scheduled_at)}</span>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="truncate text-sm font-medium">{m.title}</span>
                      <span className="truncate text-xs text-muted">
                        {m.project_name} · {t.meetingStatus[m.status]}
                      </span>
                    </span>
                    <MemoStatusBadge status={m.memo_status} />
                  </Link>
                ))
              )}
            </section>

            <section className="panel flex flex-col gap-2.5 p-[18px]">
              <h2 className="text-[15px] font-semibold">
                {t.dashboard.highIssues} / {t.dashboard.highRisks.toLowerCase()}
              </h2>
              {highCount === 0 ? (
                <p className="text-sm text-muted">{t.dashboard.emptyIssues}</p>
              ) : (
                <>
                  {data.high_priority_issues.map((i) => (
                    <Link key={i.id} href={`/meetings/${i.meeting_id}/memo`} className="flex items-start gap-2.5 border-t border-line py-2.5">
                      <Badge tone="warning">{t.memo.kind.issue}</Badge>
                      <span className="flex flex-col gap-0.5">
                        <span className="text-sm">{i.description}</span>
                        <span className="text-xs text-muted">
                          {i.code} · {i.meeting_title} · {t.priority[i.priority]}
                        </span>
                      </span>
                    </Link>
                  ))}
                  {data.high_priority_risks.map((r) => (
                    <Link key={r.id} href={`/meetings/${r.meeting_id}/memo`} className="flex items-start gap-2.5 border-t border-line py-2.5">
                      <Badge tone="danger">{t.memo.kind.risk}</Badge>
                      <span className="flex flex-col gap-0.5">
                        <span className="text-sm">{r.description}</span>
                        <span className="text-xs text-muted">
                          {r.code} · {r.meeting_title} · {t.priority[r.severity]}
                        </span>
                      </span>
                    </Link>
                  ))}
                </>
              )}
            </section>

            <section className="panel flex flex-col gap-2.5 p-[18px]">
              <h2 className="text-[15px] font-semibold">{t.dashboard.activity}</h2>
              {data.recent_activity.length === 0 ? (
                <p className="text-sm text-muted">{t.dashboard.emptyActivity}</p>
              ) : (
                data.recent_activity.map((a, i) => (
                  <div key={i} className="grid grid-cols-[96px_minmax(0,1fr)] gap-2.5 py-1 text-[13px]">
                    <span className="font-mono text-xs text-subtle">{formatDateTime(a.created_at)}</span>
                    <span>
                      <b className="font-semibold">{a.actor ?? t.common.none}</b> <span className="font-mono text-xs">{a.action}</span>
                      <span className="block text-xs text-muted">{a.project_name}</span>
                    </span>
                  </div>
                ))
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
