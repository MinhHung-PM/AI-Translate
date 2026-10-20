"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Alert, Chip, EmptyState, FilterPill, Input, PageHeader, Pagination, Select, Spinner, cn, pillControl } from "@/components/ui";
import { PriorityBadge, VerificationBadge } from "@/components/shared/status";
import { ProjectFilter } from "@/components/shared/project-select";
import { api } from "@/lib/api";
import { errorMessage, formatDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { ActionItem, ActionStatus, Page, Priority } from "@/lib/types";

const PAGE_SIZE = 25;
const STATUSES: ActionStatus[] = ["open", "in_progress", "blocked", "done", "cancelled"];
// Status select is tinted like a pill so the table scans by colour.
const STATUS_TINT: Record<ActionStatus, string> = {
  open: "border-line-strong bg-surface-2 text-ink",
  in_progress: "border-transparent bg-info-soft text-info",
  blocked: "border-transparent bg-danger-soft text-danger",
  done: "border-transparent bg-success-soft text-success",
  cancelled: "border-line bg-transparent text-muted",
};
const COLS = "grid-cols-[minmax(0,1fr)_132px] md:grid-cols-[minmax(0,1fr)_110px_120px_90px_104px_140px]";

export default function ActionTrackerPage() {
  const params = useSearchParams();
  const [projectId, setProjectId] = useState("");
  const [status, setStatus] = useState<ActionStatus | "">("");
  const [priority, setPriority] = useState<Priority | "">("");
  const [owner, setOwner] = useState("");
  const [dueFrom, setDueFrom] = useState("");
  const [dueTo, setDueTo] = useState("");
  const [overdue, setOverdue] = useState(params.get("overdue") === "1");
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const { data, error: loadError, loading, reload } = useApi<Page<ActionItem>>("/action-items", {
    project_id: projectId,
    status: status ? [status] : undefined,
    priority: priority ? [priority] : undefined,
    owner,
    due_from: dueFrom,
    due_to: dueTo,
    overdue: overdue || undefined,
    mine: mine || undefined,
    page,
    page_size: PAGE_SIZE,
  });

  async function updateStatus(item: ActionItem, next: ActionStatus) {
    setError(null);
    try {
      await api.patch(`/action-items/${item.id}`, { status: next });
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const resetPage = () => setPage(1);

  return (
    <>
      <PageHeader eyebrow={`${t.actions.scope}${data ? ` · ${data.total} ${t.actions.countSuffix}` : ""}`} title={t.actions.title} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <FilterPill label={t.actions.project}>
          <ProjectFilter value={projectId} onChange={(v) => (setProjectId(v), resetPage())} className={pillControl} />
        </FilterPill>
        <FilterPill label={t.actions.owner}>
          <Input placeholder={t.common.all} value={owner} onChange={(e) => (setOwner(e.target.value), resetPage())} aria-label={t.actions.owner} className={`${pillControl} w-28`} />
        </FilterPill>
        <FilterPill label={t.actions.dueFrom}>
          <Input type="date" value={dueFrom} onChange={(e) => (setDueFrom(e.target.value), resetPage())} aria-label={t.actions.dueFrom} className={pillControl} />
        </FilterPill>
        <FilterPill label={t.actions.dueTo}>
          <Input type="date" value={dueTo} onChange={(e) => (setDueTo(e.target.value), resetPage())} aria-label={t.actions.dueTo} className={pillControl} />
        </FilterPill>
        <FilterPill label={t.memo.fields.priority}>
          <Select value={priority} onChange={(e) => (setPriority(e.target.value as Priority | ""), resetPage())} aria-label={t.memo.fields.priority} className={pillControl}>
            <option value="">{t.common.all}</option>
            {(["critical", "high", "medium", "low"] as const).map((p) => (
              <option key={p} value={p}>
                {t.priority[p]}
              </option>
            ))}
          </Select>
        </FilterPill>
        <FilterPill label={t.memo.fields.status}>
          <Select value={status} onChange={(e) => (setStatus(e.target.value as ActionStatus | ""), resetPage())} aria-label={t.memo.fields.status} className={pillControl}>
            <option value="">{t.common.all}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t.actionStatus[s]}
              </option>
            ))}
          </Select>
        </FilterPill>
        <Chip on={mine} onClick={() => (setMine(!mine), resetPage())}>
          {t.actions.onlyMine}
        </Chip>
        <Chip on={overdue} tone="danger" onClick={() => (setOverdue(!overdue), resetPage())}>
          {t.actions.onlyOverdue}
        </Chip>
      </div>
      {(error || loadError) && (
        <Alert tone="danger" fred="sad" className="mb-3">
          {error ?? errorMessage(loadError)}
        </Alert>
      )}
      {loading && !data && <Spinner label={t.common.loading} />}
      {data && (
        <div role="table" aria-label={t.actions.title} className="overflow-hidden rounded-[14px] border border-line bg-surface">
          <div role="row" className={cn("grid gap-3 border-b border-line bg-surface-2 px-4 py-2.5 eyebrow text-muted", COLS)}>
            <span role="columnheader">{t.actions.task}</span>
            <span role="columnheader" className="hidden md:block">
              {t.memo.fields.owner}
            </span>
            <span role="columnheader" className="hidden md:block">
              {t.memo.fields.due}
            </span>
            <span role="columnheader" className="hidden md:block">
              {t.memo.fields.priority}
            </span>
            <span role="columnheader" className="hidden md:block">
              {t.memo.fields.verification}
            </span>
            <span role="columnheader">{t.memo.fields.status}</span>
          </div>
          {data.items.length === 0 ? (
            <div className="p-5">
              <EmptyState fred="happy" title={t.actions.empty} hint={t.actions.emptyHint} />
            </div>
          ) : (
            <div data-testid="action-rows">
              {data.items.map((a) => {
                const done = a.status === "done" || a.status === "cancelled";
                return (
                  <div key={a.id} role="row" className={cn("grid items-center gap-3 border-b border-line px-4 py-3 text-sm last:border-b-0", COLS, a.is_overdue && "bg-danger-soft/40")}>
                    <span role="cell" className="flex min-w-0 flex-col gap-0.5">
                      <span className={cn("font-medium", done && "text-muted line-through")}>
                        <span className="mr-1.5 font-mono text-[11px] font-normal text-subtle no-underline">{a.code}</span>
                        {a.description}
                      </span>
                      <span className="flex flex-wrap gap-x-2 text-xs">
                        <Link href={`/meetings/${a.meeting_id}/memo`} className="text-info">
                          {a.meeting_title}
                        </Link>
                        {a.sources[0] && (
                          <Link href={`/meetings/${a.meeting_id}?entry=${a.sources[0].entry_id}`} className="text-info">
                            {t.common.source} #{a.sources[0].sequence} ↗
                          </Link>
                        )}
                        <span className="text-muted">{a.project_name}</span>
                      </span>
                    </span>
                    <span role="cell" className="hidden text-[13px] md:block">
                      {a.owner_text ?? <span className="text-muted">{t.common.none}</span>}
                    </span>
                    <span role="cell" className={cn("hidden font-mono text-xs md:block", a.is_overdue ? "text-danger" : "text-muted")}>
                      {a.due_date ? formatDate(a.due_date) : (a.due_text ?? t.common.none)}
                      {a.is_overdue && ` · ${t.actions.overdue.toLowerCase()}`}
                    </span>
                    <span role="cell" className="hidden md:block">
                      <PriorityBadge priority={a.priority} />
                    </span>
                    <span role="cell" className="hidden md:block">
                      <VerificationBadge status={a.verification_status} />
                    </span>
                    <span role="cell">
                      <select
                        value={a.status}
                        onChange={(e) => void updateStatus(a, e.target.value as ActionStatus)}
                        aria-label={`${t.memo.fields.status} ${a.code}`}
                        className={cn("w-full rounded-full border px-2.5 py-1 text-xs", STATUS_TINT[a.status])}
                      >
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {t.actionStatus[s]}
                          </option>
                        ))}
                      </select>
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
      {data && <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />}
    </>
  );
}
