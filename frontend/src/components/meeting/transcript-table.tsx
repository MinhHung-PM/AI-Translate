"use client";

import { useEffect, useState } from "react";
import { Alert, Badge, Button, Dialog, Field, Fred, Textarea, cn } from "@/components/ui";
import { TranslationStatusBadge } from "@/components/shared/status";
import { api } from "@/lib/api";
import { errorMessage, formatMs } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { Language, TranscriptEntry } from "@/lib/types";

interface Props {
  entries: TranscriptEntry[];
  target: Language;
  editable: boolean;
  selected?: Set<string>;
  onToggle?: (id: string) => void;
  /** Select / clear every row on the page. */
  onToggleAll?: (on: boolean) => void;
  onChanged?: () => void;
  /** Re-translate one line (side panel "Dịch lại"). */
  onRetranslate?: (id: string) => void;
  highlightId?: string | null;
}

const SPEAKER_TEXT = ["text-spk1", "text-spk2", "text-spk3", "text-info"];

function speakerColour(label: string | null): string {
  if (!label) return "text-muted";
  let h = 0;
  for (let i = 0; i < label.length; i++) h = (h * 31 + label.charCodeAt(i)) >>> 0;
  return SPEAKER_TEXT[h % SPEAKER_TEXT.length];
}

/**
 * Bilingual transcript: time, speaker, original, translation, status. When editable, clicking a row
 * opens it in a sticky side panel where the translation is edited in place (Fred flags ambiguity).
 */
export function TranscriptTable({ entries, target, editable, selected, onToggle, onToggleAll, onChanged, onRetranslate, highlightId }: Props) {
  const [current, setCurrent] = useState<string | null>(highlightId ?? null);
  const [editOriginal, setEditOriginal] = useState<TranscriptEntry | null>(null);
  const active = editable ? (entries.find((e) => e.id === current) ?? entries[0] ?? null) : null;

  useEffect(() => {
    if (!highlightId) return;
    document.getElementById(`entry-${highlightId}`)?.scrollIntoView({ block: "center" });
  }, [highlightId, entries.length]);

  const allOn = !!selected && entries.length > 0 && entries.every((e) => selected.has(e.id));

  const table = (
    <div className="min-w-0 overflow-x-auto rounded-[14px] border border-line bg-surface">
      <table className="w-full table-fixed border-collapse text-sm" data-testid="transcript-table">
        <thead className="bg-surface-2 text-left font-mono text-[10.5px] tracking-wider text-muted uppercase">
          <tr>
            {onToggle && (
              <th className="w-9 border-b border-line px-3 py-2.5">
                {onToggleAll && <input type="checkbox" aria-label={t.workspace.selectAll} checked={allOn} onChange={() => onToggleAll(!allOn)} className="accent-accent" />}
              </th>
            )}
            <th className="w-[88px] border-b border-line px-2 py-2.5 font-medium">{t.workspace.time}</th>
            <th className="w-[104px] border-b border-line px-2 py-2.5 font-medium">{t.workspace.speaker}</th>
            <th className="hidden border-b border-line px-3 py-2.5 font-medium md:table-cell">{t.workspace.original}</th>
            <th className="border-b border-line px-3 py-2.5 font-medium">
              {t.workspace.translation} · {target}
            </th>
            <th className="w-[100px] border-b border-line px-3 py-2.5 font-medium">{t.workspace.state}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => {
            const tr = e.translation;
            const on = active?.id === e.id;
            return (
              <tr
                key={e.id}
                id={`entry-${e.id}`}
                onClick={editable ? () => setCurrent(e.id) : undefined}
                aria-selected={editable ? on : undefined}
                className={cn(
                  "align-top",
                  editable && "cursor-pointer hover:bg-surface-2/50",
                  on && "bg-surface-2 shadow-[inset_3px_0_0_var(--info)]",
                  highlightId === e.id && !on && "bg-accent-soft",
                )}
                data-testid="transcript-row"
              >
                {onToggle && (
                  <td className="border-b border-line px-3 py-2.5" onClick={(ev) => ev.stopPropagation()}>
                    <input type="checkbox" aria-label={`#${e.sequence}`} checked={selected?.has(e.id) ?? false} onChange={() => onToggle(e.id)} className="mt-1 accent-accent" />
                  </td>
                )}
                <td className="border-b border-line px-2 py-2.5 font-mono text-xs text-muted">
                  <div>#{e.sequence}</div>
                  {e.start_ms !== null && <div className="tabular-nums">{formatMs(e.start_ms)}</div>}
                </td>
                <td className={cn("truncate border-b border-line px-2 py-2.5 text-[13px] font-semibold", speakerColour(e.speaker_label))} title={e.speaker_label ?? undefined}>
                  {e.speaker_label ?? <span className="font-normal text-muted">{t.workspace.speakerUnknown}</span>}
                </td>
                <td className="hidden border-b border-line px-3 py-2.5 leading-normal text-muted md:table-cell">
                  <p className="break-words whitespace-pre-wrap">{e.original_text}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    {e.source_language && <Badge>{e.source_language}</Badge>}
                    {e.original_edited && <Badge tone="warning">{t.common.edit}</Badge>}
                    {e.source_metadata.is_demo === true && <Badge tone="warning">DEMO</Badge>}
                  </div>
                </td>
                <td className="border-b border-line px-3 py-2.5 leading-normal">
                  {tr?.text ? (
                    <p className="break-words whitespace-pre-wrap">{tr.text}</p>
                  ) : tr?.status === "failed" ? (
                    <p className="text-danger">{t.workspace.failedLine}</p>
                  ) : (
                    <p className="text-subtle">{t.common.none}</p>
                  )}
                  {/* Narrow screens: the original moves under the translation. */}
                  <p className="mt-1 text-xs text-muted md:hidden">{e.original_text}</p>
                  {!editable && tr?.ambiguity_note && (
                    <p className="mt-1 text-xs text-warning">
                      ⚠ {t.workspace.ambiguity}: {tr.ambiguity_note}
                    </p>
                  )}
                  {tr?.status === "failed" && tr.error_message && <p className="mt-1 text-xs text-danger">{tr.error_message}</p>}
                </td>
                <td className="border-b border-line px-3 py-2.5" title={tr?.ambiguity_note ?? undefined}>
                  <div className="flex flex-col items-start gap-1">
                    {tr?.ambiguity_note ? (
                      <span className="text-xs whitespace-nowrap text-warning">⚠ {t.workspace.ambiguous}</span>
                    ) : (
                      <TranslationStatusBadge status={tr?.status ?? "pending"} />
                    )}
                    {tr?.is_user_edited ? (
                      <span className="text-xs whitespace-nowrap text-info" title={t.workspace.userEdited}>
                        ✎ {t.workspace.edited}
                      </span>
                    ) : (
                      tr?.text && <Badge tone="info">AI</Badge>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );

  if (!editable) return table;

  return (
    <div className="grid items-start gap-3.5 xl:grid-cols-[minmax(0,1fr)_340px]">
      {table}
      {active && <LineEditor key={active.id} entry={active} target={target} onChanged={onChanged} onRetranslate={onRetranslate} onEditOriginal={() => setEditOriginal(active)} />}
      <OriginalDialog entry={editOriginal} onClose={() => setEditOriginal(null)} onChanged={onChanged} />
    </div>
  );
}

/** Side panel for the selected line: original, editable translation, ambiguity hint from Fred. */
function LineEditor({ entry, target, onChanged, onRetranslate, onEditOriginal }: { entry: TranscriptEntry; target: Language; onChanged?: () => void; onRetranslate?: (id: string) => void; onEditOriginal: () => void }) {
  const tr = entry.translation;
  const [value, setValue] = useState(tr?.text ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.put(`/transcript-entries/${entry.id}/translation`, { text: value, target_language: target });
      setSaved(true);
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="sticky top-4 flex flex-col gap-2.5 rounded-[14px] border border-line bg-surface p-4" aria-label={t.workspace.editTranslation} data-testid="line-editor">
      <span className="eyebrow text-muted">
        {t.workspace.line} #{entry.sequence}
        {entry.start_ms !== null && ` · ${formatMs(entry.start_ms)}`} · {entry.speaker_label ?? t.workspace.speakerUnknown}
      </span>
      <p className="text-[15px] leading-relaxed break-words">{entry.original_text}</p>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">{t.workspace.manualTranslation}</span>
        <Textarea
          rows={3}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setSaved(false);
          }}
          className="border-info text-[15px]"
        />
      </label>
      {tr?.ambiguity_note && (
        <div className="flex items-start gap-2.5">
          <Fred pose="thinking" className="h-[60px] w-auto shrink-0" />
          <div className="rounded-[12px_12px_12px_4px] bg-warning-soft px-3 py-2.5 text-[13px] leading-normal">
            <b className="text-warning">{t.workspace.ambiguity} · </b>
            {tr.ambiguity_note}
          </div>
        </div>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="inverse" size="sm" onClick={() => void save()} loading={busy} disabled={!value.trim() || value === (tr?.text ?? "")}>
          {t.common.save}
        </Button>
        {onRetranslate && (
          <Button size="sm" onClick={() => onRetranslate(entry.id)}>
            {t.workspace.retranslateLine}
          </Button>
        )}
        <button type="button" onClick={onEditOriginal} className="text-[13px] text-info">
          {t.workspace.editOriginal}
        </button>
        {saved && <span className="text-xs text-success">✓ {t.workspace.savedLine}</span>}
      </div>
    </aside>
  );
}

function OriginalDialog({ entry, onClose, onChanged }: { entry: TranscriptEntry | null; onClose: () => void; onChanged?: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [openFor, setOpenFor] = useState<string | null>(null);
  // Load the line's text when the dialog opens for a new entry.
  if (entry && openFor !== entry.id) {
    setOpenFor(entry.id);
    setValue(entry.original_text);
    setError(null);
  }

  async function save() {
    if (!entry) return;
    setBusy(true);
    try {
      await api.patch(`/transcript-entries/${entry.id}`, { original_text: value });
      setOpenFor(null);
      onClose();
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={entry !== null}
      onClose={() => {
        setOpenFor(null);
        onClose();
      }}
      title={t.workspace.editOriginal}
      footer={
        <>
          <Button onClick={onClose}>{t.common.cancel}</Button>
          <Button variant="primary" onClick={() => void save()} loading={busy} disabled={!value.trim()}>
            {t.common.save}
          </Button>
        </>
      }
    >
      <div className="space-y-2">
        <Field label={t.workspace.original}>{(id) => <Textarea id={id} rows={5} value={value} onChange={(ev) => setValue(ev.target.value)} />}</Field>
        {error && <Alert tone="danger">{error}</Alert>}
      </div>
    </Dialog>
  );
}
