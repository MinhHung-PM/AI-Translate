"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert, Card, Checkbox, EmptyState, Input, PageHeader, Pagination, Select, Spinner, Table, cn } from "@/components/ui";
import { PriorityBadge, VerificationBadge } from "@/components/shared/status";
import { ProjectFilter } from "@/components/shared/project-select";
import { api } from "@/lib/api";
import { errorMessage, formatDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { ActionItem, ActionStatus, Page, Priority } from "@/lib/types";

const PAGE_SIZE = 25;
const STATUSES: ActionStatus[] = ["open", "in_progress", "blocked", "done", "cancelled"];

export default function ActionTrackerPage() {
  const [projectId, setProjectId] = useState("");
  const [status, setStatus] = useState<ActionStatus | "">("");
  const [priority, setPriority] = useState<Priority | "">("");
  const [owner, setOwner] = useState("");
  const [dueFrom, setDueFrom] = useState("");
  const [dueTo, setDueTo] = useState("");
  const [overdue, setOverdue] = useState(false);
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
      <PageHeader title={t.actions.title} />
      <div className="mb-3 grid grid-cols-2 gap-2 rounded-lg border border-line bg-white p-3 md:grid-cols-4 xl:grid-cols-8">
        <ProjectFilter value={projectId} onChange={(v) => (setProjectId(v), resetPage())} />
        <Select value={status} onChange={(e) => (setStatus(e.target.value as ActionStatus | ""), resetPage())} aria-label={t.memo.fields.status}>
          <option value="">{t.memo.fields.status}: {t.common.all}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t.actionStatus[s]}
            </option>
          ))}
        </Select>
        <Select value={priority} onChange={(e) => (setPriority(e.target.value as Priority | ""), resetPage())} aria-label={t.memo.fields.priority}>
          <option value="">{t.memo.fields.priority}: {t.common.all}</option>
          {(["critical", "high", "medium", "low"] as const).map((p) => (
            <option key={p} value={p}>
              {t.priority[p]}
            </option>
          ))}
        </Select>
        <Input placeholder={t.actions.owner} value={owner} onChange={(e) => (setOwner(e.target.value), resetPage())} aria-label={t.actions.owner} />
        <Input type="date" value={dueFrom} onChange={(e) => (setDueFrom(e.target.value), resetPage())} aria-label={t.actions.dueFrom} title={t.actions.dueFrom} />
        <Input type="date" value={dueTo} onChange={(e) => (setDueTo(e.target.value), resetPage())} aria-label={t.actions.dueTo} title={t.actions.dueTo} />
        <Checkbox label={t.actions.onlyOverdue} checked={overdue} onChange={(e) => (setOverdue(e.target.checked), resetPage())} />
        <Checkbox label={t.actions.onlyMine} checked={mine} onChange={(e) => (setMine(e.target.checked), resetPage())} />
      </div>
      {(error || loadError) && <Alert tone="danger" className="mb-3">{error ?? errorMessage(loadError)}</Alert>}
      {loading && !data && <Spinner label={t.common.loading} />}
      {data && (
        <Card bodyClassName="p-0">
          {data.items.length === 0 ? (
            <div className="p-4">
              <EmptyState title={t.actions.empty} />
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>{t.memo.fields.description}</th>
                  <th>{t.memo.fields.owner}</th>
                  <th>{t.memo.fields.due}</th>
                  <th>{t.memo.fields.priority}</th>
                  <th>{t.memo.fields.status}</th>
                  <th>{t.memo.fields.verification}</th>
                  <th>{t.actions.meeting}</th>
                </tr>
              </thead>
              <tbody data-testid="action-rows">
                {data.items.map((a) => (
                  <tr key={a.id} className={cn(a.is_overdue && "bg-red-50/60")}>
                    <td className="font-mono text-xs whitespace-nowrap text-muted">{a.code}</td>
                    <td className="max-w-md">
                      <p>{a.description}</p>
                      {a.sources[0] && (
                        <Link href={`/meetings/${a.meeting_id}?entry=${a.sources[0].entry_id}`} className="text-xs text-brand-700 hover:underline">
                          {t.common.source} #{a.sources[0].sequence}
                        </Link>
                      )}
                    </td>
                    <td>{a.owner_text ?? <span className="text-muted">{t.common.none}</span>}</td>
                    <td className={cn("whitespace-nowrap", a.is_overdue && "font-medium text-red-700")}>
                      {a.due_date ? formatDate(a.due_date) : (a.due_text ?? t.common.none)}
                      {a.is_overdue && <span className="ml-1 text-xs">({t.actions.overdue})</span>}
                    </td>
                    <td>
                      <PriorityBadge priority={a.priority} />
                    </td>
                    <td>
                      <Select value={a.status} onChange={(e) => void updateStatus(a, e.target.value as ActionStatus)} className="h-8 w-36 text-xs" aria-label={`${t.memo.fields.status} ${a.code}`}>
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {t.actionStatus[s]}
                          </option>
                        ))}
                      </Select>
                    </td>
                    <td>
                      <VerificationBadge status={a.verification_status} />
                    </td>
                    <td className="text-xs">
                      <Link href={`/meetings/${a.meeting_id}/memo`} className="text-brand-700 hover:underline">
                        {a.meeting_title}
                      </Link>
                      <p className="text-muted">{a.project_name}</p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      )}
      {data && <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />}
    </>
  );
}
