"use client";

import { useEffect, useState } from "react";
import { Alert, Badge, Button, Dialog, EmptyState, Field, Fred, FredSays, Spinner, Textarea, cn } from "@/components/ui";
import { MeetingHeader } from "@/components/meeting/meeting-header";
import { useMeeting } from "@/components/meeting/use-meeting";
import type { ItemKind } from "@/components/memo/item-fields";
import { ItemList } from "@/components/memo/item-list";
import { DiscussionEditor, NextMeetingEditor, PMViewEditor, QuestionsEditor, SummaryEditor, type Narrative } from "@/components/memo/narrative";
import { api, ApiError, downloadFile } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { Member, Memo } from "@/lib/types";

function toNarrative(m: Memo): Narrative {
  return {
    executive_summary: m.executive_summary,
    discussion: m.discussion,
    open_questions: m.open_questions,
    next_meeting: m.next_meeting,
    pm_view: m.pm_view ?? {},
  };
}

function cleanNarrative(n: Narrative) {
  return {
    executive_summary: n.executive_summary,
    discussion: n.discussion
      .filter((d) => d.topic.trim())
      .map((d) => ({ ...d, points: d.points.map((p) => p.trim()).filter(Boolean) })),
    open_questions: n.open_questions.filter((q) => q.question.trim()),
    ...(n.next_meeting && (n.next_meeting.when_text || n.next_meeting.agenda.some((a) => a.trim()))
      ? { next_meeting: { ...n.next_meeting, agenda: n.next_meeting.agenda.map((a) => a.trim()).filter(Boolean) } }
      : { clear_next_meeting: true }),
    pm_view: n.pm_view,
  };
}

export default function MemoPage() {
  const { id, data: meeting, reload: reloadMeeting } = useMeeting();
  const memoQuery = useApi<Memo>(`/meetings/${id}/memo`);
  const memo = memoQuery.data;
  const members = useApi<Member[]>(meeting ? `/projects/${meeting.project_id}/members` : null);
  // Local unsaved edits; when null, the narrative shown is the server version.
  const [draft, setDraft] = useState<Narrative | null>(null);
  const dirty = draft !== null;
  const narrative = draft ?? (memo ? toNarrative(memo) : null);
  const setNarrative = (n: Narrative) => setDraft(n);
  const setDirty = (d: boolean) => {
    if (!d) setDraft(null);
  };
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<"approve" | "reject" | null>(null);
  const [comment, setComment] = useState("");
  const [exportOpen, setExportOpen] = useState(false);

  // While the AI is generating, poll until it finishes.
  const reloadMemo = memoQuery.reload;
  useEffect(() => {
    if (memo?.status !== "generating") return;
    const timer = setInterval(() => void reloadMemo(), 1500);
    return () => clearInterval(timer);
  }, [memo?.status, reloadMemo]);

  async function run<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(label);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError(errorMessage(err));
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  function applyMemo(m: Memo | undefined) {
    if (!m) return;
    memoQuery.setData(m);
    void reloadMeeting();
  }

  async function generate() {
    if (memo && memo.generation_count > 0 && !window.confirm(t.memo.regenerateConfirm)) return;
    await run("generate", async () => {
      await api.post(`/meetings/${id}/memo/generate`);
      setDirty(false);
      await memoQuery.reload();
    });
  }

  /** Returns false when saving failed (the error stays on screen). */
  async function saveDraft(): Promise<boolean> {
    if (!memo || !narrative) return true;
    const m = await run("save", () => api.put<Memo>(`/memos/${memo.id}`, cleanNarrative(narrative)));
    if (!m) return false;
    setDirty(false);
    applyMemo(m);
    return true;
  }

  async function transition(action: "submit" | "approve" | "reject" | "reopen", body?: unknown) {
    if (!memo) return;
    // Never submit/approve a memo without the edits on screen: stop if saving them failed.
    if (dirty && action !== "reopen" && !(await saveDraft())) return;
    const m = await run(action, () => api.post<Memo>(`/memos/${memo.id}/${action}`, body));
    applyMemo(m);
    setReview(null);
    setComment("");
  }

  // Item operations: errors are rethrown so the editor dialog can show them.
  async function onCreate(kind: ItemKind, body: Record<string, unknown>) {
    if (!memo) return;
    try {
      applyMemo(await api.post<Memo>(`/memos/${memo.id}/${kind}`, body));
    } catch (err) {
      throw new Error(errorMessage(err));
    }
  }
  async function onPatch(kind: ItemKind, itemId: string, body: Record<string, unknown>) {
    try {
      applyMemo(await api.patch<Memo>(`/${kind}/${itemId}`, body));
    } catch (err) {
      setError(errorMessage(err));
      throw new Error(errorMessage(err));
    }
  }
  async function onDelete(kind: ItemKind, itemId: string) {
    await run("delete", async () => applyMemo(await api.del<Memo>(`/${kind}/${itemId}`)));
  }

  if (!meeting) return <Spinner label={t.common.loading} />;
  const notFound = memoQuery.error instanceof ApiError && memoQuery.error.status === 404;
  const total = memo ? memo.decisions.length + memo.action_items.length + memo.issues.length + memo.risks.length : 0;
  const unverified = memo?.unreviewed_items ?? 0;
  const fredSays = !memo
    ? ""
    : memo.status === "approved"
      ? t.memo.fredApproved
      : memo.status === "rejected"
        ? t.memo.fredRejected
        : unverified
          ? t.memo.fredUnverified.replace("{total}", String(total)).replace("{n}", String(unverified))
          : t.memo.fredVerified;

  return (
    <>
      <MeetingHeader meeting={meeting} eyebrow={t.memo.eyebrow} />
      {error && (
        <Alert tone="danger" fred="sad" className="mb-3">
          {error}
        </Alert>
      )}

      {notFound && (
        <EmptyState
          fred={meeting.entry_count ? "clipboard" : "thinking"}
          title={meeting.entry_count ? t.memo.none : t.workspace.noTranscript}
          action={
            meeting.permissions.edit && meeting.entry_count > 0 ? (
              <Button variant="primary" onClick={() => void generate()} loading={busy === "generate"} data-testid="generate-memo">
                {t.memo.generate}
              </Button>
            ) : undefined
          }
        />
      )}
      {memoQuery.loading && !memo && !notFound && <Spinner label={t.common.loading} />}

      {memo && memo.status === "generating" && <Generating entries={meeting.entry_count} />}
      {memo && memo.status === "failed" && (
        <Alert tone="danger" fred="sad" title={t.memo.failed} className="mb-3">
          <p>{memo.generation_error}</p>
          {meeting.permissions.edit && (
            <Button size="sm" className="mt-2" onClick={() => void generate()} loading={busy === "generate"}>
              {t.common.retry}
            </Button>
          )}
        </Alert>
      )}

      {memo && narrative && !["generating", "failed"].includes(memo.status) && (
        <div className="flex flex-col gap-4">
          <div className="sticky top-0 z-[3] flex flex-wrap items-center gap-2.5 rounded-[14px] border border-line bg-surface px-3.5 py-3">
            <ol className="flex min-w-64 flex-1 flex-wrap items-center gap-1.5 text-xs" aria-label={t.memo.fields.status}>
              {(memo.status === "rejected" ? (["draft", "in_review", "rejected"] as const) : (["draft", "in_review", "approved"] as const)).map((k, i, arr) => {
                const on = memo.status === k;
                const done = (arr as readonly string[]).indexOf(memo.status) > i;
                return (
                  <li key={k} className="flex items-center gap-1.5" aria-current={on ? "step" : undefined}>
                    <span
                      className={cn(
                        "rounded-full px-2.5 py-1 whitespace-nowrap",
                        on ? (k === "rejected" ? "bg-danger-soft font-bold text-danger" : k === "approved" ? "bg-success-soft font-bold text-success" : "bg-accent-soft font-bold text-accent-text") : done ? "text-ink" : "text-subtle",
                      )}
                    >
                      {t.memo.flow[k]}
                    </span>
                    {i < arr.length - 1 && (
                      <span className="text-subtle" aria-hidden>
                        →
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
            <span className="text-[13px] whitespace-nowrap text-muted">
              {dirty ? <span className="text-warning">{t.memo.unsaved}</span> : unverified ? t.memo.unverified.replace("{n}", String(unverified)) : t.memo.allVerified}
            </span>
            {memo.reviewed_at && (
              <span className="text-xs text-muted">
                {memo.status === "approved" ? t.memo.approvedBy : t.memoStatus.rejected}: {formatDateTime(memo.reviewed_at)}
              </span>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {memo.permissions.regenerate && (
                <Button size="sm" variant="ghost" onClick={() => void generate()} loading={busy === "generate"}>
                  {t.memo.regenerate}
                </Button>
              )}
              {memo.permissions.edit && (
                <Button size="sm" onClick={() => void saveDraft()} loading={busy === "save"} disabled={!dirty} data-testid="save-draft">
                  {t.memo.saveDraft}
                </Button>
              )}
              {memo.permissions.submit && (
                <Button size="sm" variant="primary" onClick={() => void transition("submit")} loading={busy === "submit"} data-testid="submit-memo">
                  {t.memo.submit}
                </Button>
              )}
              {memo.permissions.reject && (
                <Button size="sm" variant="danger" onClick={() => setReview("reject")}>
                  {t.memo.rejectMemo}
                </Button>
              )}
              {memo.permissions.approve && (
                <Button size="sm" variant="primary" onClick={() => setReview("approve")} data-testid="approve-memo">
                  {t.memo.approve}
                </Button>
              )}
              {memo.permissions.reopen && (
                <Button size="sm" onClick={() => void transition("reopen")} loading={busy === "reopen"}>
                  {t.memo.reopen}
                </Button>
              )}
              {memo.permissions.export ? (
                <div className="relative">
                  <Button size="sm" onClick={() => setExportOpen(!exportOpen)} aria-expanded={exportOpen} aria-haspopup="menu" data-testid="export-menu">
                    {t.common.export} ▾
                  </Button>
                  {exportOpen && (
                    <div role="menu" className="absolute top-10 right-0 z-[5] flex min-w-44 flex-col rounded-xl border border-line bg-surface p-1.5 shadow-[var(--shadow)]">
                      {(["md", "html", "json"] as const).map((fmt) => (
                        <button
                          key={fmt}
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setExportOpen(false);
                            void run("export", () => downloadFile(`/memos/${memo.id}/export`, { format: fmt }));
                          }}
                          className="rounded-lg px-2.5 py-2 text-left text-[13px] hover:bg-surface-2"
                          data-testid={`export-${fmt}`}
                        >
                          {fmt === "md" ? `${t.memo.exportMd} (.md)` : fmt === "html" ? t.memo.exportHtml : t.memo.exportJson}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <span className="text-xs text-muted">{t.memo.exportOnlyApproved}</span>
              )}
            </div>
          </div>

          {memo.review_comment && (
            <Alert tone={memo.status === "rejected" ? "danger" : "neutral"} fred={memo.status === "rejected" ? "sad" : undefined}>
              <b>{memo.status === "rejected" ? t.memo.rejectedBanner : t.memo.reviewComment}:</b> {memo.review_comment}
            </Alert>
          )}

          <div className="grid items-start gap-4 min-[1180px]:grid-cols-[minmax(0,1fr)_300px]">
            <div className="flex min-w-0 flex-col gap-4">
              <section className="panel grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-x-5 gap-y-3 p-5 text-[13px]" aria-label={t.memo.sections.info}>
                {[
                  [t.meetingForm.project, memo.meeting_info.project_name],
                  [t.meetingForm.date, `${formatDateTime(memo.meeting_info.scheduled_at, memo.meeting_info.timezone)} (${memo.meeting_info.timezone})`],
                  [t.meetingForm.sourceLanguage, `${memo.meeting_info.source_language ?? "auto"} · ${t.meetingForm.memoLanguage.toLowerCase()}: ${memo.language}`],
                  [t.meetingForm.participants, memo.meeting_info.participants.join(", ") || t.common.none],
                  [t.meetingForm.objective, memo.meeting_info.objective || t.common.none],
                ].map(([k, v]) => (
                  <div key={k} className="flex flex-col gap-0.5">
                    <span className="text-xs text-muted">{k}</span>
                    <span className="font-medium">{v}</span>
                  </div>
                ))}
                <p className="col-span-full font-mono text-[11px] text-subtle">
                  {t.memo.meta}: {memo.prompt_version} · {memo.provider}/{memo.model} · {formatDateTime(memo.generated_at)}
                </p>
              </section>

              <section className="panel flex flex-col gap-5 p-5">
                <p className="text-xs text-muted">{t.memo.aiDraftNotice}</p>
                {(
                  [
                    ["summary", t.memo.sections.summary, SummaryEditor, true],
                    ["discussion", t.memo.sections.discussion, DiscussionEditor, false],
                    ["questions", t.memo.sections.questions, QuestionsEditor, false],
                    ["next", t.memo.sections.next, NextMeetingEditor, false],
                  ] as const
                ).map(([key, title, Editor, ai]) => (
                  <div key={key} className="flex flex-col gap-2">
                    <h2 className="flex items-center gap-2 text-[15px] font-semibold">
                      {title}
                      {ai && <Badge tone="info">{t.memo.aiSuggested}</Badge>}
                    </h2>
                    <Editor value={narrative} editable={memo.permissions.edit} meetingId={id} onChange={setNarrative} />
                  </div>
                ))}
              </section>

              {(
                [
                  ["decisions", t.memo.sections.decisions, memo.decisions, t.memo.addDecision],
                  ["action-items", t.memo.sections.actions, memo.action_items, t.memo.addAction],
                  ["issues", t.memo.sections.issues, memo.issues, t.memo.addIssue],
                  ["risks", t.memo.sections.risks, memo.risks, t.memo.addRisk],
                ] as const
              ).map(([kind, title, items, addLabel]) => (
                <section key={kind} className="panel flex flex-col gap-2 px-5 py-[18px]">
                  <h2 className="text-[15px] font-semibold">
                    {title} <span className="font-normal text-muted">· {items.length}</span>
                  </h2>
                  <ItemList
                    kind={kind}
                    items={[...items]}
                    meetingId={id}
                    members={members.data ?? []}
                    canEditContent={memo.permissions.edit}
                    canTrack={memo.permissions.track_actions}
                    addLabel={addLabel}
                    onCreate={onCreate}
                    onPatch={onPatch}
                    onDelete={onDelete}
                  />
                </section>
              ))}
            </div>

            <div className="flex flex-col gap-4 min-[1180px]:sticky min-[1180px]:top-20">
              <div className="flex flex-col items-center">
                <FredSays className="self-stretch text-[13px]">{fredSays}</FredSays>
                <Fred pose={memo.status === "approved" ? "happy" : memo.status === "rejected" ? "sad" : "clipboard"} alt={t.fred.clipboardAlt} className="w-[min(100%,240px)]" />
              </div>
              <section className="panel flex flex-col gap-2.5 p-[18px]">
                <h2 className="text-[15px] font-semibold">{t.memo.sections.pm}</h2>
                <PMViewEditor value={narrative} editable={memo.permissions.edit} meetingId={id} onChange={setNarrative} />
              </section>
            </div>
          </div>
        </div>
      )}

      <Dialog
        open={review !== null}
        onClose={() => setReview(null)}
        title={review === "approve" ? t.memo.approve : t.memo.rejectMemo}
        footer={
          <>
            <Button onClick={() => setReview(null)}>{t.common.cancel}</Button>
            <Button
              variant={review === "approve" ? "primary" : "danger"}
              loading={busy === review}
              onClick={() => review && void transition(review, { comment: comment || null })}
              data-testid="confirm-review"
            >
              {review === "approve" ? t.memo.approve : t.memo.rejectMemo}
            </Button>
          </>
        }
      >
        {memo && review === "approve" && memo.unreviewed_items > 0 && (
          <Alert tone="warning" className="mb-2">
            {memo.unreviewed_items} {t.memo.unreviewedWarning}
          </Alert>
        )}
        <Field label={review === "reject" ? t.memo.rejectNote : t.memo.reviewComment}>
          {(fid) => <Textarea id={fid} rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder={review === "reject" ? t.memo.rejectPlaceholder : undefined} />}
        </Field>
      </Dialog>
    </>
  );
}

/** While the AI writes the minutes: Fred thinks, steps tick by (indicative — the server reports no progress). */
function Generating({ entries }: { entries: number }) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setStep((s) => Math.min(s + 1, t.memo.generatingSteps.length - 1)), 2500);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="flex flex-wrap items-center gap-6 rounded-[22px] border border-line bg-surface p-7" role="status" aria-live="polite">
      <Fred pose="thinking" alt={t.fred.thinkingAlt} className="h-[170px] w-auto animate-floaty" />
      <div className="flex min-w-56 flex-1 flex-col gap-3">
        <span className="eyebrow text-[11px] tracking-[.08em] text-accent-text">{t.memo.generating}</span>
        <span className="font-display text-xl leading-tight font-semibold">{t.memo.generatingTitle}</span>
        <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
          <div className="h-full bg-accent transition-[width] duration-700" style={{ width: `${((step + 1) / (t.memo.generatingSteps.length + 1)) * 100}%` }} />
        </div>
        {t.memo.generatingSteps.map((label, i) => (
          <span key={label} className={cn("text-[13px]", i <= step ? "text-ink" : "text-subtle")}>
            {i < step ? "✓" : i === step ? "›" : "·"} {i === 0 ? `${label} (${entries})` : label}
          </span>
        ))}
      </div>
    </div>
  );
}
