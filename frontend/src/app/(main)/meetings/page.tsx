"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert, Badge, Card, EmptyState, Input, PageHeader, Pagination, Select, Spinner, Table } from "@/components/ui";
import { MeetingStatusBadge, MemoStatusBadge } from "@/components/shared/status";
import { ProjectFilter } from "@/components/shared/project-select";
import { errorMessage, formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { Meeting, MeetingPlatform, MemoStatus, Page } from "@/lib/types";

const PAGE_SIZE = 20;

export default function HistoryPage() {
  const [q, setQ] = useState("");
  const [projectId, setProjectId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [memoStatus, setMemoStatus] = useState<MemoStatus | "">("");
  const [platform, setPlatform] = useState<MeetingPlatform | "">("");
  const [page, setPage] = useState(1);
  const { data, error, loading } = useApi<Page<Meeting>>("/meetings", {
    q,
    project_id: projectId,
    date_from: from ? `${from}T00:00:00Z` : undefined,
    date_to: to ? `${to}T23:59:59Z` : undefined,
    memo_status: memoStatus,
    platform,
    page,
    page_size: PAGE_SIZE,
  });
  const reset = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setPage(1);
  };

  return (
    <>
      <PageHeader title={t.history.title} />
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-6">
        <Input type="search" placeholder={t.history.searchPlaceholder} value={q} onChange={(e) => reset(setQ)(e.target.value)} className="col-span-2" aria-label={t.common.search} />
        <ProjectFilter value={projectId} onChange={reset(setProjectId)} />
        <Input type="date" value={from} onChange={(e) => reset(setFrom)(e.target.value)} aria-label={t.common.from} />
        <Input type="date" value={to} onChange={(e) => reset(setTo)(e.target.value)} aria-label={t.common.to} />
        <div className="col-span-2 grid grid-cols-2 gap-2 md:col-span-1 md:grid-cols-1">
          <Select value={memoStatus} onChange={(e) => reset(setMemoStatus)(e.target.value as MemoStatus | "")} aria-label={t.history.columns.memo}>
            <option value="">{t.history.columns.memo}: {t.common.all}</option>
            {(["draft", "in_review", "approved", "rejected", "failed"] as const).map((s) => (
              <option key={s} value={s}>
                {t.memoStatus[s]}
              </option>
            ))}
          </Select>
          <Select value={platform} onChange={(e) => reset(setPlatform)(e.target.value as MeetingPlatform | "")} aria-label={t.history.columns.platform}>
            <option value="">{t.history.columns.platform}: {t.common.all}</option>
            {(["manual_import", "teams", "zoom", "google_meet"] as const).map((p) => (
              <option key={p} value={p}>
                {t.platform[p]}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      {loading && !data && <Spinner label={t.common.loading} />}
      {data && (
        <Card bodyClassName="p-0">
          {data.items.length === 0 ? (
            <div className="p-4">
              <EmptyState title={t.history.empty} />
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>{t.history.columns.title}</th>
                  <th>{t.history.columns.project}</th>
                  <th>{t.history.columns.date}</th>
                  <th>{t.history.columns.platform}</th>
                  <th>{t.history.columns.status}</th>
                  <th>{t.history.columns.memo}</th>
                  <th className="text-right">{t.history.columns.entries}</th>
                  <th />
                </tr>
              </thead>
              <tbody data-testid="history-rows">
                {data.items.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <Link href={`/meetings/${m.id}`} className="font-medium text-brand-700 hover:underline">
                        {m.title}
                      </Link>
                    </td>
                    <td className="text-muted">{m.project_name}</td>
                    <td className="whitespace-nowrap text-muted">{formatDateTime(m.scheduled_at, m.timezone)}</td>
                    <td>
                      <Badge tone={m.platform_status === "available" ? "neutral" : "warning"}>{t.platform[m.platform]}</Badge>
                    </td>
                    <td>
                      <MeetingStatusBadge status={m.status} />
                    </td>
                    <td>
                      <MemoStatusBadge status={m.memo_status} />
                    </td>
                    <td className="text-right tabular-nums">{m.entry_count}</td>
                    <td className="whitespace-nowrap text-xs">
                      {m.permissions.view_transcript && (
                        <Link href={`/meetings/${m.id}`} className="mr-2 text-brand-700 hover:underline">
                          {t.workspace.tabs.transcript}
                        </Link>
                      )}
                      <Link href={`/meetings/${m.id}/memo`} className="text-brand-700 hover:underline">
                        {t.workspace.tabs.memo}
                      </Link>
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
