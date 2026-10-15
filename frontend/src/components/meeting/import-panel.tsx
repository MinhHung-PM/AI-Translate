"use client";

import { useRef, useState } from "react";
import { Alert, Button, Checkbox, Field, Select, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import { t } from "@/lib/i18n";

export function ImportPanel({ meetingId, hasTranscript, onImported }: { meetingId: string; hasTranscript: boolean; onImported: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [lang, setLang] = useState("");
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const file = fileRef.current?.files?.[0];
      let res: { entry_count: number; detected_language: string | null; format: string };
      if (file) {
        const fd = new FormData();
        fd.append("file", file);
        if (lang) fd.append("source_language", lang);
        fd.append("replace", String(replace));
        res = await api.post(`/meetings/${meetingId}/transcript/upload`, fd);
      } else {
        res = await api.post(`/meetings/${meetingId}/transcript/text`, { text, source_language: lang || null, replace });
      }
      setResult(`${res.format.toUpperCase()} · ${res.entry_count} ${t.workspace.entries}${res.detected_language ? ` · ${t.workspace.detected}: ${res.detected_language}` : ""}`);
      setText("");
      if (fileRef.current) fileRef.current.value = "";
      onImported();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">{t.workspace.importHint}</p>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label={t.workspace.chooseFile}>
          {(id) => (
            <input
              id={id}
              ref={fileRef}
              type="file"
              accept=".txt,.srt,.vtt,.json,text/plain,text/vtt,application/json"
              className="text-sm file:mr-3 file:rounded file:border file:border-line file:bg-white file:px-2 file:py-1 file:text-sm"
              data-testid="transcript-file"
            />
          )}
        </Field>
        <Field label={t.workspace.sourceOverride}>
          {(id) => (
            <Select id={id} value={lang} onChange={(e) => setLang(e.target.value)}>
              <option value="">{t.languages.auto}</option>
              <option value="ja">{t.languages.ja}</option>
              <option value="vi">{t.languages.vi}</option>
              <option value="en">{t.languages.en}</option>
            </Select>
          )}
        </Field>
        {hasTranscript && (
          <div className="flex items-end pb-2">
            <Checkbox label={t.workspace.replace} checked={replace} onChange={(e) => setReplace(e.target.checked)} />
          </div>
        )}
      </div>
      <Field label={t.workspace.pasteText}>
        {(id) => <Textarea id={id} rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder={t.workspace.pastePlaceholder} />}
      </Field>
      {error && <Alert tone="danger">{error}</Alert>}
      {result && <Alert tone="success">{result}</Alert>}
      <Button variant="primary" onClick={() => void submit()} loading={busy} data-testid="import-submit">
        {t.workspace.upload}
      </Button>
    </div>
  );
}
