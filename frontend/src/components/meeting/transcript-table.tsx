"use client";

import { useEffect, useState } from "react";
import { Alert, Badge, Button, Dialog, Field, Textarea, cn } from "@/components/ui";
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
  onChanged?: () => void;
  highlightId?: string | null;
}

type EditMode = { entry: TranscriptEntry; kind: "original" | "translation" } | null;

export function TranscriptTable({ entries, target, editable, selected, onToggle, onChanged, highlightId }: Props) {
  const [edit, setEdit] = useState<EditMode>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!highlightId) return;
    document.getElementById(`entry-${highlightId}`)?.scrollIntoView({ block: "center" });
  }, [highlightId, entries.length]);

  function open(entry: TranscriptEntry, kind: "original" | "translation") {
    setEdit({ entry, kind });
    setValue(kind === "original" ? entry.original_text : (entry.translation?.text ?? ""));
    setError(null);
  }

  async function save() {
    if (!edit) return;
    setBusy(true);
    try {
      if (edit.kind === "original") await api.patch(`/transcript-entries/${edit.entry.id}`, { original_text: value });
      else await api.put(`/transcript-entries/${edit.entry.id}/translation`, { text: value, target_language: target });
      setEdit(null);
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="overflow-x-auto rounded-lg border border-line bg-white">
        <table className="w-full table-fixed border-collapse text-sm" data-testid="transcript-table">
          <thead className="bg-gray-50 text-left text-xs text-muted">
            <tr>
              {onToggle && <th className="w-8 border-b border-line px-2 py-2" />}
              <th className="w-28 border-b border-line px-2 py-2 font-medium">#</th>
              <th className="border-b border-line px-3 py-2 font-medium">{t.workspace.original}</th>
              <th className="border-b border-line px-3 py-2 font-medium">
                {t.workspace.translation} ({t.languages[target]})
              </th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => {
              const tr = e.translation;
              return (
                <tr key={e.id} id={`entry-${e.id}`} className={cn("align-top", highlightId === e.id && "bg-amber-50")} data-testid="transcript-row">
                  {onToggle && (
                    <td className="border-b border-line px-2 py-2">
                      <input type="checkbox" aria-label={`#${e.sequence}`} checked={selected?.has(e.id) ?? false} onChange={() => onToggle(e.id)} className="accent-brand-600" />
                    </td>
                  )}
                  <td className="border-b border-line px-2 py-2 text-xs text-muted">
                    <div className="font-mono">#{e.sequence}</div>
                    {e.start_ms !== null && <div className="tabular-nums">{formatMs(e.start_ms)}</div>}
                    <div className="mt-0.5 truncate font-medium text-ink" title={e.speaker_label ?? undefined}>
                      {e.speaker_label ?? <span className="text-muted">{t.workspace.speakerUnknown}</span>}
                    </div>
                  </td>
                  <td className="border-b border-line px-3 py-2">
                    <p className="whitespace-pre-wrap break-words">{e.original_text}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      {e.source_language && <Badge>{e.source_language}</Badge>}
                      {e.original_edited && <Badge tone="warning">{t.common.edit}</Badge>}
                      {e.source_metadata.is_demo === true && <Badge tone="warning">DEMO</Badge>}
                      {editable && (
                        <button type="button" className="text-xs text-brand-700 hover:underline" onClick={() => open(e, "original")}>
                          {t.workspace.editOriginal}
                        </button>
                      )}
                    </div>
                  </td>
                  <td className="border-b border-line bg-slate-50/60 px-3 py-2">
                    {tr?.text ? <p className="whitespace-pre-wrap break-words">{tr.text}</p> : <p className="text-muted">{t.common.none}</p>}
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      {tr ? <TranslationStatusBadge status={tr.status} /> : <TranslationStatusBadge status="pending" />}
                      {tr?.is_user_edited ? <Badge title={t.workspace.userEdited}>✎ {t.workspace.userEdited}</Badge> : tr?.text && <Badge tone="brand">AI</Badge>}
                      {editable && (
                        <button type="button" className="text-xs text-brand-700 hover:underline" onClick={() => open(e, "translation")}>
                          {t.workspace.editTranslation}
                        </button>
                      )}
                    </div>
                    {tr?.ambiguity_note && (
                      <p className="mt-1 text-xs text-amber-800">
                        ⚠ {t.workspace.ambiguity}: {tr.ambiguity_note}
                      </p>
                    )}
                    {tr?.status === "failed" && tr.error_message && <p className="mt-1 text-xs text-red-700">{tr.error_message}</p>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Dialog
        open={edit !== null}
        onClose={() => setEdit(null)}
        title={edit?.kind === "original" ? t.workspace.editOriginal : t.workspace.editTranslation}
        footer={
          <>
            <Button onClick={() => setEdit(null)}>{t.common.cancel}</Button>
            <Button variant="primary" onClick={() => void save()} loading={busy} disabled={!value.trim()}>
              {t.common.save}
            </Button>
          </>
        }
      >
        {edit && (
          <div className="space-y-2">
            {edit.kind === "translation" && <p className="rounded bg-gray-50 p-2 text-sm text-muted">{edit.entry.original_text}</p>}
            <Field label={edit.kind === "original" ? t.workspace.original : t.workspace.translation}>
              {(id) => <Textarea id={id} rows={5} value={value} onChange={(ev) => setValue(ev.target.value)} />}
            </Field>
            {error && <Alert tone="danger">{error}</Alert>}
          </div>
        )}
      </Dialog>
    </>
  );
}
