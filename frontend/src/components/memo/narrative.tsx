"use client";

import dynamic from "next/dynamic";
import { Badge, Button, Field, Input, Textarea } from "@/components/ui";
import { t } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import { PM_KEYS, type DiscussionTopic, type NextMeeting, type OpenQuestion, type PMView } from "@/lib/types";
import { EntryIdRefs } from "./source-refs";

// The Markdown editor touches `window`, so it is loaded client-side only.
const MDEditor = dynamic(() => import("@uiw/react-md-editor"), { ssr: false, loading: () => <Textarea rows={8} disabled /> });

export interface Narrative {
  executive_summary: string;
  discussion: DiscussionTopic[];
  open_questions: OpenQuestion[];
  next_meeting: NextMeeting | null;
  pm_view: PMView;
}

interface Props {
  value: Narrative;
  onChange: (v: Narrative) => void;
  editable: boolean;
  meetingId: string;
}

export function SummaryEditor({ value, onChange, editable }: Props) {
  const { theme } = usePrefs();
  if (!editable) {
    return <MDPreview source={value.executive_summary} />;
  }
  return (
    <div data-color-mode={theme} data-testid="summary-editor">
      <MDEditor
        value={value.executive_summary}
        onChange={(v) => onChange({ ...value, executive_summary: v ?? "" })}
        preview="edit"
        height={220}
        textareaProps={{ "aria-label": t.memo.sections.summary }}
      />
    </div>
  );
}

const MDMarkdown = dynamic(() => import("@uiw/react-md-editor").then((m) => m.default.Markdown), { ssr: false });

function MDPreview({ source }: { source: string }) {
  const { theme } = usePrefs();
  return (
    <div data-color-mode={theme} className="max-w-[72ch] text-[15px] leading-relaxed">
      <MDMarkdown source={source || t.common.none} />
    </div>
  );
}

export function DiscussionEditor({ value, onChange, editable, meetingId }: Props) {
  const topics = value.discussion;
  const update = (i: number, patch: Partial<DiscussionTopic>) =>
    onChange({ ...value, discussion: topics.map((tp, idx) => (idx === i ? { ...tp, ...patch } : tp)) });
  if (!editable) {
    return topics.length ? (
      <div className="space-y-3">
        {topics.map((tp, i) => (
          <div key={i}>
            <h4 className="text-sm font-medium">
              {tp.topic}
              <EntryIdRefs meetingId={meetingId} ids={tp.source_entry_ids} />
            </h4>
            <ul className="ml-5 list-disc text-sm">
              {tp.points.map((p, j) => (
                <li key={j}>{p}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    ) : (
      <p className="text-sm text-muted">{t.common.none}</p>
    );
  }
  return (
    <div className="space-y-3">
      {topics.map((tp, i) => (
        <div key={i} className="rounded-xl border border-line p-3">
          <div className="flex items-end gap-2">
            <Field label={t.memo.fields.topic} className="flex-1">
              {(id) => <Input id={id} value={tp.topic} onChange={(e) => update(i, { topic: e.target.value })} />}
            </Field>
            <Button size="sm" variant="danger" onClick={() => onChange({ ...value, discussion: topics.filter((_, idx) => idx !== i) })}>
              {t.common.delete}
            </Button>
          </div>
          <Field label={t.memo.fields.points} className="mt-2">
            {(id) => <Textarea id={id} rows={3} value={tp.points.join("\n")} onChange={(e) => update(i, { points: e.target.value.split("\n") })} />}
          </Field>
          <EntryIdRefs meetingId={meetingId} ids={tp.source_entry_ids} />
        </div>
      ))}
      <Button size="sm" onClick={() => onChange({ ...value, discussion: [...topics, { topic: "", points: [], source_entry_ids: [] }] })}>
        + {t.memo.addTopic}
      </Button>
    </div>
  );
}

export function QuestionsEditor({ value, onChange, editable, meetingId }: Props) {
  const qs = value.open_questions;
  if (!editable) {
    return qs.length ? (
      <ul className="ml-5 list-disc text-sm">
        {qs.map((q, i) => (
          <li key={i}>
            {q.question}
            <EntryIdRefs meetingId={meetingId} ids={q.source_entry_ids} />
          </li>
        ))}
      </ul>
    ) : (
      <p className="text-sm text-muted">{t.common.none}</p>
    );
  }
  return (
    <div className="space-y-2">
      {qs.map((q, i) => (
        <div key={i} className="flex items-start gap-2">
          <Textarea
            rows={1}
            aria-label={t.memo.fields.question}
            value={q.question}
            onChange={(e) => onChange({ ...value, open_questions: qs.map((x, idx) => (idx === i ? { ...x, question: e.target.value } : x)) })}
          />
          <EntryIdRefs meetingId={meetingId} ids={q.source_entry_ids} />
          <Button size="sm" variant="danger" onClick={() => onChange({ ...value, open_questions: qs.filter((_, idx) => idx !== i) })}>
            ×
          </Button>
        </div>
      ))}
      <Button size="sm" onClick={() => onChange({ ...value, open_questions: [...qs, { question: "", source_entry_ids: [] }] })}>
        + {t.memo.addQuestion}
      </Button>
    </div>
  );
}

export function NextMeetingEditor({ value, onChange, editable }: Props) {
  const nm = value.next_meeting ?? { when_text: "", agenda: [], source_entry_ids: [] };
  if (!editable) {
    return value.next_meeting ? (
      <div className="text-sm">
        <p>{nm.when_text || t.common.none}</p>
        <ul className="ml-5 list-disc">
          {nm.agenda.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ul>
      </div>
    ) : (
      <p className="text-sm text-muted">{t.common.none}</p>
    );
  }
  return (
    <div className="grid gap-2 md:grid-cols-2">
      <Field label={t.memo.fields.when}>
        {(id) => <Input id={id} value={nm.when_text ?? ""} onChange={(e) => onChange({ ...value, next_meeting: { ...nm, when_text: e.target.value } })} />}
      </Field>
      <Field label={t.memo.fields.agenda}>
        {(id) => <Textarea id={id} rows={2} value={nm.agenda.join("\n")} onChange={(e) => onChange({ ...value, next_meeting: { ...nm, agenda: e.target.value.split("\n") } })} />}
      </Field>
    </div>
  );
}

/** PM view: one row per dimension (cost, scope, quality, schedule, escalation, satisfaction). */
export function PMViewEditor({ value, onChange, editable, meetingId }: Props) {
  const pm = value.pm_view;
  return (
    <div className="flex flex-col">
      {PM_KEYS.map((key) => {
        const a = pm[key];
        return (
          <div key={key} className="grid grid-cols-[96px_minmax(0,1fr)] gap-2.5 border-t border-line py-2 text-[13px] first:border-t-0">
            <span className="text-muted">{t.memo.pm[key]}</span>
            <div className="flex min-w-0 flex-col gap-1">
              {editable ? (
                <Textarea
                  rows={2}
                  aria-label={t.memo.pm[key]}
                  value={a?.assessment ?? ""}
                  className="min-h-0 px-2 py-1.5 text-[13px]"
                  onChange={(e) => {
                    const text = e.target.value;
                    // A human edit replaces the AI basis label.
                    onChange({ ...value, pm_view: { ...pm, [key]: text.trim() ? { assessment: text, basis: "human", source_entry_ids: a?.source_entry_ids ?? [] } : null } });
                  }}
                />
              ) : (
                <p className="leading-snug">{a?.assessment ?? <span className="text-muted">{t.common.none}</span>}</p>
              )}
              {a && (
                <span className="flex flex-wrap items-center gap-1">
                  <Badge tone={a.basis === "evidence" ? "success" : a.basis === "human" ? "neutral" : "warning"}>{t.memo.pm[a.basis]}</Badge>
                  <EntryIdRefs meetingId={meetingId} ids={a.source_entry_ids} />
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
