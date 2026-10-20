"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Card, Chip, EmptyState, FilterPill, Input, Pagination, Select, Spinner, pillControl } from "@/components/ui";
import { MeetingSourceSelector } from "@/components/integrations/MeetingSourceSelector";
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
  const [speaker, setSpeaker] = useState("");
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
  const progressDone = job ? job.progress_done : (stats.data?.done ?? 0);
  const progressTotal = job ? Math.max(job.progress_total, 1) : (stats.data?.total ?? 0);
  const pct = progressTotal ? Math.round((progressDone / progressTotal) * 100) : 0;

  const items = entries.data?.items ?? [];
  const speakers = [...new Set(items.map((e) => e.speaker_label).filter((x): x is string => !!x))].slice(0, 6);
  const shown = speaker ? items.filter((e) => e.speaker_label === speaker) : items;
  const statusChips: { value: TranslationStatus | ""; label: string; tone?: "danger" }[] = [
    { value: "", label: t.common.all },
    { value: "pending", label: `${t.translationStatus.pending}${stats.data ? ` · ${stats.data.pending}` : ""}` },
    { value: "done", label: t.translationStatus.done },
    { value: "failed", label: `${t.translationStatus.failed}${stats.data ? ` · ${stats.data.failed}` : ""}`, tone: "danger" },
  ];

  return (
    <>
      <MeetingHeader meeting={meeting} />
      {meeting.content_purged_at && <Alert tone="warning" className="mb-3">{t.workspace.purged}</Alert>}
      {!canView && <Alert tone="info">{t.memo.restricted}</Alert>}

      {canView && (
        <div className="flex flex-col gap-4">
          {(editable || meeting.platform !== "manual_import") && (
            <Card title={t.source.title}>
              <MeetingSourceSelector meetingId={id} editable={editable} platform={meeting.platform} onImported={refreshAll} />
            </Card>
          )}
          {(!hasTranscript || showImport) && editable && (
            <Card title={t.workspace.import}>
              <ImportPanel meetingId={id} hasTranscript={hasTranscript} onImported={refreshAll} />
            </Card>
          )}
          {!hasTranscript && !editable && <EmptyState fred="thinking" title={t.workspace.noTranscript} />}

          {hasTranscript && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  type="search"
                  placeholder={`${t.workspace.searchPlaceholder}`}
                  value={q}
                  onChange={(e) => {
                    setQ(e.target.value);
                    setPage(1);
                  }}
                  className="h-9 max-w-sm min-w-48 flex-1 bg-surface"
                  aria-label={t.common.search}
                />
                <div className="flex flex-wrap gap-1.5" role="group" aria-label={t.history.columns.status}>
                  {statusChips.map((c) => (
                    <Chip
                      key={c.value || "all"}
                      on={status === c.value}
                      tone={c.tone}
                      onClick={() => {
                        setStatus(c.value);
                        setPage(1);
                      }}
                    >
                      {c.label}
                    </Chip>
                  ))}
                </div>
                {speakers.length > 1 && (
                  <div className="flex flex-wrap gap-1.5" role="group" aria-label={t.workspace.speaker}>
                    {speakers.map((sp) => (
                      <Chip key={sp} on={speaker === sp} onClick={() => setSpeaker(speaker === sp ? "" : sp)}>
                        {sp}
                      </Chip>
                    ))}
                  </div>
                )}
                <FilterPill label={t.workspace.targetLanguage} className="ml-auto">
                  <Select value={lang} onChange={(e) => setTarget(e.target.value as Language)} className={pillControl} aria-label={t.workspace.targetLanguage}>
                    <option value="vi">{t.languages.vi}</option>
                    <option value="ja">{t.languages.ja}</option>
                    <option value="en">{t.languages.en}</option>
                  </Select>
                </FilterPill>
              </div>

              <div className="flex flex-wrap items-center gap-2.5 rounded-xl border border-line bg-surface px-3.5 py-2.5">
                <span className="text-[13px] whitespace-nowrap" data-testid="translation-stats">
                  {t.translationStatus.done}: <b>{job ? job.progress_done : (stats.data?.done ?? 0)}</b>/{job ? job.progress_total : (stats.data?.total ?? 0)}
                  {jobId && <span className="text-info"> · {t.workspace.jobRunning}</span>}
                </span>
                <div className="h-1.5 min-w-28 flex-1 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-label={t.workspace.progress} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                  <div className="h-full bg-success transition-all" style={{ width: `${pct}%` }} />
                </div>
                {editable && (
                  <>
                    <Button variant="primary" size="sm" onClick={() => void startTranslation({})} disabled={!!jobId} data-testid="translate-all">
                      {jobId ? t.workspace.jobRunning : t.workspace.translateAll}
                    </Button>
                    <Button size="sm" onClick={() => void startTranslation({ entry_ids: [...selected] })} disabled={!!jobId || selected.size === 0}>
                      {t.workspace.translateSelected} ({selected.size})
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => void startTranslation({ only_failed: true })} disabled={!!jobId || !stats.data?.failed}>
                      {t.workspace.retryFailed} ({stats.data?.failed ?? 0})
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => void startTranslation({ force: true })} disabled={!!jobId}>
                      {t.workspace.retranslateAll}
                    </Button>
                    <Button size="sm" onClick={() => setShowImport((v) => !v)}>
                      {t.workspace.import}
                    </Button>
                  </>
                )}
                <select
                  aria-label={t.workspace.exportRecord}
                  value=""
                  onChange={(e) => e.target.value && void downloadFile(`/meetings/${id}/export`, { format: e.target.value }).catch((err) => setActionError(errorMessage(err)))}
                  className="h-8 rounded-full border border-line-strong bg-transparent px-3 text-[13px]"
                >
                  <option value="">{t.workspace.exportRecord}</option>
                  <option value="md">Markdown</option>
                  <option value="csv">CSV</option>
                  <option value="json">JSON</option>
                </select>
                {editable && (
                  <Button variant="inverse" size="sm" onClick={() => void generateMemo()} data-testid="generate-memo">
                    {t.workspace.generateMemo}
                  </Button>
                )}
              </div>
              {actionError && (
                <Alert tone="danger" fred="sad">
                  {actionError}
                </Alert>
              )}
              <p className="text-xs text-muted">{t.workspace.aiNotice}</p>

              {entries.error && <Alert tone="danger">{errorMessage(entries.error)}</Alert>}
              {entries.data && shown.length === 0 && <EmptyState fred="thinking" title={t.workspace.noResults} hint={t.workspace.noResultsHint} />}
              {entries.data && shown.length > 0 && (
                <>
                  <TranscriptTable
                    entries={shown}
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
                    onToggleAll={editable ? (on) => setSelected(on ? new Set(shown.map((e) => e.id)) : new Set()) : undefined}
                    onRetranslate={editable && !jobId ? (eid) => void startTranslation({ entry_ids: [eid], force: true }) : undefined}
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
