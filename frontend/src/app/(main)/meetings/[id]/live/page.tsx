"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, EmptyState, Field, Input, ProgressBar, Spinner, Textarea } from "@/components/ui";
import { MeetingHeader } from "@/components/meeting/meeting-header";
import { TranscriptTable } from "@/components/meeting/transcript-table";
import { useMeeting } from "@/components/meeting/use-meeting";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { LiveSession, TranscriptEntry } from "@/lib/types";

interface Feed {
  session: LiveSession | null;
  entries: TranscriptEntry[];
}

/** Live-style view. In Workstream 1 the only source is the REPLAY DEMO connector;
 * real connectors (Workstream 2) will feed the same polling endpoint. */
export default function LiveReplayPage() {
  const { id, data: meeting, reload: reloadMeeting } = useMeeting();
  const [feed, setFeed] = useState<Feed | null>(null);
  const [text, setText] = useState("");
  const [interval, setIntervalSec] = useState("1.5");
  const [translate, setTranslate] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const running = feed?.session?.status === "running";

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const f = await api.get<Feed>(`/meetings/${id}/live`);
        if (!cancelled) setFeed(f);
        if (!cancelled && f.session?.status === "running") timer = setTimeout(poll, 1000);
        else if (!cancelled && f.session && f.session.status !== "running") void reloadMeeting();
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      }
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, feed?.session?.id, feed?.session?.status === "running"]);

  useEffect(() => {
    if (running) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [feed?.entries.length, running]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      const file = fileRef.current?.files?.[0];
      if (file) fd.append("file", file);
      else fd.append("text", text);
      fd.append("interval_seconds", interval);
      fd.append("translate", String(translate));
      const session = await api.post<LiveSession>(`/meetings/${id}/replay`, fd);
      setFeed({ session, entries: [] });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!feed?.session) return;
    try {
      const session = await api.post<LiveSession>(`/live-sessions/${feed.session.id}/stop`);
      setFeed({ ...feed, session });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (!meeting) return <Spinner label={t.common.loading} />;
  const canStart = meeting.permissions.edit && meeting.entry_count === 0 && !feed?.session;

  return (
    <>
      <MeetingHeader meeting={meeting} />
      <div className="mb-4 rounded-md border-2 border-dashed border-amber-400 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-900" role="status" data-testid="demo-banner">
        {t.live.banner}
      </div>
      {error && <Alert tone="danger" className="mb-3">{error}</Alert>}

      {canStart && (
        <Card title={t.live.start} className="mb-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Field label={t.workspace.chooseFile}>
              {(fid) => <input id={fid} ref={fileRef} type="file" accept=".txt,.srt,.vtt,.json" className="text-sm" />}
            </Field>
            <Field label={t.live.interval}>
              {(fid) => <Input id={fid} type="number" min={0} max={10} step={0.5} value={interval} onChange={(e) => setIntervalSec(e.target.value)} />}
            </Field>
            <div className="flex items-end pb-2">
              <Checkbox label={t.live.translate} checked={translate} onChange={(e) => setTranslate(e.target.checked)} />
            </div>
          </div>
          <Field label={t.workspace.pasteText} className="mt-3">
            {(fid) => <Textarea id={fid} rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder={t.workspace.pastePlaceholder} />}
          </Field>
          <Button variant="primary" className="mt-3" onClick={() => void start()} loading={busy} data-testid="start-replay">
            {t.live.start}
          </Button>
        </Card>
      )}
      {!canStart && !feed?.session && meeting.entry_count > 0 && <Alert tone="info">{t.live.requiresEmpty}</Alert>}

      {feed?.session && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-white p-3">
            <Badge tone="warning">DEMO · {feed.session.connector}</Badge>
            <span className="text-sm">
              {t.live.status}: <b data-testid="replay-status">{feed.session.status}</b>
            </span>
            <div className="min-w-48 flex-1">
              <ProgressBar value={feed.session.entries_emitted} max={feed.session.entries_total} label={t.live.emitted} />
            </div>
            {running && (
              <Button variant="danger" onClick={() => void stop()}>
                {t.live.stop}
              </Button>
            )}
          </div>
          {feed.entries.length === 0 ? (
            <EmptyState title={t.live.waiting} />
          ) : (
            <TranscriptTable entries={feed.entries} target={meeting.target_language} editable={false} />
          )}
          <div ref={bottomRef} />
        </div>
      )}
    </>
  );
}
