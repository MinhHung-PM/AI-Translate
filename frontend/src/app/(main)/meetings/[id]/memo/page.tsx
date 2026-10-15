"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Card, Dialog, EmptyState, Field, Spinner, Textarea } from "@/components/ui";
import { MeetingHeader } from "@/components/meeting/meeting-header";
import { useMeeting } from "@/components/meeting/use-meeting";
import { MemoStatusBadge } from "@/components/shared/status";
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

  async function saveDraft() {
    if (!memo || !narrative) return;
    const m = await run("save", () => api.put<Memo>(`/memos/${memo.id}`, cleanNarrative(narrative)));
    if (m) {
      setDirty(false);
      applyMemo(m);
    }
  }

  async function transition(action: "submit" | "approve" | "reject" | "reopen", body?: unknown) {
    if (!memo) return;
    if (dirty && action !== "reopen") await saveDraft();
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

  return (
    <>
      <MeetingHeader meeting={meeting} />
      {error && <Alert tone="danger" className="mb-3">{error}</Alert>}

      {notFound && (
        <EmptyState
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

      {memo && memo.status === "generating" && (
        <Card>
          <Spinner label={t.memo.generating} />
        </Card>
      )}
      {memo && memo.status === "failed" && (
        <Alert tone="danger" title={t.memo.failed} className="mb-3">
          <p>{memo.generation_error}</p>
          {meeting.permissions.edit && (
            <Button size="sm" className="mt-2" onClick={() => void generate()} loading={busy === "generate"}>
              {t.common.retry}
            </Button>
          )}
        </Alert>
      )}

      {memo && narrative && !["generating", "failed"].includes(memo.status) && (
        <div className="space-y-4">
          <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-white/95 p-3 backdrop-blur">
            <MemoStatusBadge status={memo.status} />
            {memo.reviewed_at && (
              <span className="text-xs text-muted">
                {memo.status === "approved" ? t.memo.approvedBy : t.memoStatus.rejected}: {formatDateTime(memo.reviewed_at)}
              </span>
            )}
            {dirty && <span className="text-xs text-amber-700">{t.memo.unsaved}</span>}
            <div className="ml-auto flex flex-wrap gap-2">
              {memo.permissions.edit && (
                <Button onClick={() => void saveDraft()} loading={busy === "save"} disabled={!dirty} data-testid="save-draft">
                  {t.memo.saveDraft}
                </Button>
              )}
              {memo.permissions.regenerate && (
                <Button variant="ghost" onClick={() => void generate()} loading={busy === "generate"}>
                  {t.memo.regenerate}
                </Button>
              )}
              {memo.permissions.submit && (
                <Button onClick={() => void transition("submit")} loading={busy === "submit"} data-testid="submit-memo">
                  {t.memo.submit}
                </Button>
              )}
              {memo.permissions.reject && (
                <Button variant="danger" onClick={() => setReview("reject")}>
                  {t.memo.rejectMemo}
                </Button>
              )}
              {memo.permissions.approve && (
                <Button variant="primary" onClick={() => setReview("approve")} data-testid="approve-memo">
                  {t.memo.approve}
                </Button>
              )}
              {memo.permissions.reopen && (
                <Button onClick={() => void transition("reopen")} loading={busy === "reopen"}>
                  {t.memo.reopen}
                </Button>
              )}
              {memo.permissions.export ? (
                (["md", "html", "json"] as const).map((fmt) => (
                  <Button key={fmt} size="md" onClick={() => void run("export", () => downloadFile(`/memos/${memo.id}/export`, { format: fmt }))} data-testid={`export-${fmt}`}>
                    {t.common.export} {fmt === "md" ? t.memo.exportMd : fmt === "html" ? t.memo.exportHtml : t.memo.exportJson}
                  </Button>
                ))
              ) : (
                <span className="self-center text-xs text-muted">{t.memo.exportOnlyApproved}</span>
              )}
            </div>
          </div>

          <Alert tone="info">{t.memo.aiDraftNotice}</Alert>
          {memo.unreviewed_items > 0 && memo.status !== "approved" && (
            <Alert tone="warning">
              {memo.unreviewed_items} {t.memo.unreviewedWarning}
            </Alert>
          )}
          {memo.review_comment && (
            <Alert tone={memo.status === "rejected" ? "danger" : "neutral"}>
              {t.memo.reviewComment}: {memo.review_comment}
            </Alert>
          )}

          <Card title={t.memo.sections.info}>
            <dl className="grid gap-x-6 gap-y-1 text-sm md:grid-cols-2">
              <div>
                <dt className="inline text-muted">{t.meetingForm.project}: </dt>
                <dd className="inline">{memo.meeting_info.project_name}</dd>
              </div>
              <div>
                <dt className="inline text-muted">{t.meetingForm.date}: </dt>
                <dd className="inline">
                  {formatDateTime(memo.meeting_info.scheduled_at, memo.meeting_info.timezone)} ({memo.meeting_info.timezone})
                </dd>
              </div>
              <div className="md:col-span-2">
                <dt className="inline text-muted">{t.meetingForm.participants}: </dt>
                <dd className="inline">{memo.meeting_info.participants.join(", ") || t.common.none}</dd>
              </div>
              <div className="md:col-span-2">
                <dt className="inline text-muted">{t.meetingForm.objective}: </dt>
                <dd className="inline">{memo.meeting_info.objective || t.common.none}</dd>
              </div>
              <div>
                <dt className="inline text-muted">{t.meetingForm.sourceLanguage}: </dt>
                <dd className="inline">{memo.meeting_info.source_language ? t.languages[memo.meeting_info.source_language] : t.common.none}</dd>
              </div>
              <div>
                <dt className="inline text-muted">{t.meetingForm.memoLanguage}: </dt>
                <dd className="inline">{t.languages[memo.language]}</dd>
              </div>
              <div className="text-xs text-muted md:col-span-2">
                {t.memo.meta}: {memo.prompt_version} · {memo.provider}/{memo.model} · {formatDateTime(memo.generated_at)}
              </div>
            </dl>
          </Card>

          {(
            [
              ["summary", t.memo.sections.summary, SummaryEditor],
              ["discussion", t.memo.sections.discussion, DiscussionEditor],
            ] as const
          ).map(([key, title, Editor]) => (
            <Card key={key} title={title}>
              <Editor
                value={narrative}
                editable={memo.permissions.edit}
                meetingId={id}
                onChange={setNarrative}
              />
            </Card>
          ))}

          {(
            [
              ["decisions", t.memo.sections.decisions, memo.decisions, t.memo.addDecision],
              ["action-items", t.memo.sections.actions, memo.action_items, t.memo.addAction],
              ["issues", t.memo.sections.issues, memo.issues, t.memo.addIssue],
              ["risks", t.memo.sections.risks, memo.risks, t.memo.addRisk],
            ] as const
          ).map(([kind, title, items, addLabel]) => (
            <Card key={kind} title={`${title} (${items.length})`}>
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
            </Card>
          ))}

          {(
            [
              ["questions", t.memo.sections.questions, QuestionsEditor],
              ["next", t.memo.sections.next, NextMeetingEditor],
              ["pm", t.memo.sections.pm, PMViewEditor],
            ] as const
          ).map(([key, title, Editor]) => (
            <Card key={key} title={title}>
              <Editor
                value={narrative}
                editable={memo.permissions.edit}
                meetingId={id}
                onChange={setNarrative}
              />
            </Card>
          ))}
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
        <Field label={t.memo.reviewComment}>{(fid) => <Textarea id={fid} rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />}</Field>
      </Dialog>
    </>
  );
}
