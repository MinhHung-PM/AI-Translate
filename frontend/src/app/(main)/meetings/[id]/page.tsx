"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Card, EmptyState, Input, Pagination, ProgressBar, Select, Spinner } from "@/components/ui";
import { ImportPanel } from "@/components/meeting/import-panel";
import { MeetingHeader } from "@/components/meeting/meeting-header";
import { TranscriptTable } from "@/components/meeting/transcript-table";
import { useMeeting } from "@/components/meeting/use-meeting";
import { api, downloadFile } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import { useApi, useJob } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { Job, Language, Page, TranscriptEntry, TranslationStats, TranslationStatus } from "@/lib/types";

const PAGE_SIZE = 200;

export default function TranscriptWorkspacePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const highlight = searchParams.get("entry");
  const { id, data: meeting, error: meetingError, reload: reloadMeeting } = useMeeting();
  const [target, setTarget] = useState<Language | "">("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<TranslationStatus | "">("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [jobId, setJobId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const lang = (target || meeting?.target_language || "vi") as Language;
  const canView = meeting?.permissions.view_transcript ?? false;
  const editable = meeting?.permissions.edit ?? false;

  const entries = useApi<Page<TranscriptEntry>>(meeting && canView ? `/meetings/${id}/transcript` : null, {
    target_language: lang,
    q,
    status,
    page,
    page_size: PAGE_SIZE,
  });
  const stats = useApi<TranslationStats>(meeting && canView ? `/meetings/${id}/transcript/stats` : null, { target_language: lang });

  const job = useJob(jobId, (finished: Job) => {
    setJobId(null);
    if (finished.status === "failed") setActionError(finished.error_message ?? t.workspace.jobFailed);
    void entries.reload();
    void stats.reload();
    void reloadMeeting();
  });

  async function startTranslation(body: Record<string, unknown>) {
    setActionError(null);
    try {
      const j = await api.post<Job>(`/meetings/${id}/translations`, { target_language: lang, ...body });
      setJobId(j.id);
      setSelected(new Set());
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }

  async function generateMemo() {
    setActionError(null);
    try {
      await api.post<Job>(`/meetings/${id}/memo/generate`);
      router.push(`/meetings/${id}/memo`);
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }

  function refreshAll() {
    void entries.reload();
    void stats.reload();
    void reloadMeeting();
    setShowImport(false);
  }

  if (meetingError) return <Alert tone="danger">{errorMessage(meetingError)}</Alert>;
  if (!meeting) return <Spinner label={t.common.loading} />;
  const hasTranscript = meeting.entry_count > 0;

  return (
    <>
      <MeetingHeader meeting={meeting} />
      {meeting.content_purged_at && <Alert tone="warning" className="mb-3">{t.workspace.purged}</Alert>}
      {!canView && <Alert tone="info">{t.memo.restricted}</Alert>}

      {canView && (
        <div className="space-y-4">
          {(!hasTranscript || showImport) && editable && (
            <Card title={t.workspace.import}>
              <ImportPanel meetingId={id} hasTranscript={hasTranscript} onImported={refreshAll} />
            </Card>
          )}
          {!hasTranscript && !editable && <EmptyState title={t.workspace.noTranscript} />}

          {hasTranscript && (
            <>
              <div className="flex flex-wrap items-end gap-2 rounded-lg border border-line bg-white p-3">
                <label className="text-xs text-muted">
                  {t.workspace.targetLanguage}
                  <Select value={lang} onChange={(e) => setTarget(e.target.value as Language)} className="mt-1 w-36">
                    <option value="vi">{t.languages.vi}</option>
                    <option value="ja">{t.languages.ja}</option>
                    <option value="en">{t.languages.en}</option>
                  </Select>
                </label>
                {editable && (
                  <>
                    <Button variant="primary" onClick={() => void startTranslation({})} disabled={!!jobId} data-testid="translate-all">
                      {t.workspace.translateAll}
                    </Button>
                    <Button onClick={() => void startTranslation({ entry_ids: [...selected] })} disabled={!!jobId || selected.size === 0}>
                      {t.workspace.translateSelected} ({selected.size})
                    </Button>
                    <Button onClick={() => void startTranslation({ only_failed: true })} disabled={!!jobId || !stats.data?.failed}>
                      {t.workspace.retryFailed}
                    </Button>
                    <Button variant="ghost" onClick={() => void startTranslation({ force: true })} disabled={!!jobId}>
                      {t.workspace.retranslateAll}
                    </Button>
                  </>
                )}
                <div className="ml-auto flex flex-wrap items-end gap-2">
                  {editable && (
                    <Button onClick={() => setShowImport((v) => !v)}>{t.workspace.import}</Button>
                  )}
                  <Select aria-label={t.workspace.exportRecord} value="" onChange={(e) => e.target.value && void downloadFile(`/meetings/${id}/export`, { format: e.target.value }).catch((err) => setActionError(errorMessage(err)))} className="w-40">
                    <option value="">{t.workspace.exportRecord}</option>
                    <option value="md">Markdown</option>
                    <option value="csv">CSV</option>
                    <option value="json">JSON</option>
                  </Select>
                  {editable && (
                    <Button variant="primary" onClick={() => void generateMemo()} data-testid="generate-memo">
                      {t.workspace.generateMemo}
                    </Button>
                  )}
                </div>
              </div>

              {stats.data && (
                <div className="grid gap-2 rounded-lg border border-line bg-white p-3 md:grid-cols-[1fr_auto]">
                  <ProgressBar value={job ? job.progress_done : stats.data.done} max={job ? Math.max(job.progress_total, 1) : stats.data.total} label={t.workspace.progress} />
                  <p className="text-xs text-muted" data-testid="translation-stats">
                    {t.translationStatus.done}: {stats.data.done} · {t.translationStatus.failed}: {stats.data.failed} · {t.translationStatus.pending}: {stats.data.pending}
                    {jobId && ` · ${t.workspace.jobRunning}`}
                  </p>
                </div>
              )}
              {actionError && <Alert tone="danger">{actionError}</Alert>}
              <Alert tone="info">{t.workspace.aiNotice}</Alert>

              <div className="flex flex-wrap gap-2">
                <Input
                  type="search"
                  placeholder={`${t.common.search}…`}
                  value={q}
                  onChange={(e) => {
                    setQ(e.target.value);
                    setPage(1);
                  }}
                  className="max-w-sm"
                  aria-label={t.common.search}
                />
                <Select
                  aria-label={t.history.columns.status}
                  value={status}
                  onChange={(e) => {
                    setStatus(e.target.value as TranslationStatus | "");
                    setPage(1);
                  }}
                  className="w-44"
                >
                  <option value="">{t.common.all}</option>
                  {(["pending", "done", "failed"] as const).map((s) => (
                    <option key={s} value={s}>
                      {t.translationStatus[s]}
                    </option>
                  ))}
                </Select>
              </div>

              {entries.error && <Alert tone="danger">{errorMessage(entries.error)}</Alert>}
              {entries.data && entries.data.items.length === 0 && <EmptyState title={t.workspace.noResults} />}
              {entries.data && entries.data.items.length > 0 && (
                <>
                  <TranscriptTable
                    entries={entries.data.items}
                    target={lang}
                    editable={editable}
                    selected={editable ? selected : undefined}
                    onToggle={
                      editable
                        ? (eid) =>
                            setSelected((prev) => {
                              const next = new Set(prev);
                              if (next.has(eid)) next.delete(eid);
                              else next.add(eid);
                              return next;
                            })
                        : undefined
                    }
                    onChanged={() => {
                      void entries.reload();
                      void stats.reload();
                    }}
                    highlightId={highlight}
                  />
                  <Pagination page={page} pageSize={PAGE_SIZE} total={entries.data.total} onChange={setPage} />
                </>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}
