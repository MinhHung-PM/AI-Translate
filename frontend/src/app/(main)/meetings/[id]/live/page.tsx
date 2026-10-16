"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, EmptyState, Field, Input, ProgressBar, Spinner, Textarea } from "@/components/ui";
import { MeetingHeader } from "@/components/meeting/meeting-header";
import { TranscriptTable } from "@/components/meeting/transcript-table";
import { useMeeting } from "@/components/meeting/use-meeting";
import { api } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { LiveSession, TranscriptEntry } from "@/lib/types";

interface Feed {
  session: LiveSession | null;
  entries: TranscriptEntry[];
  /** Client clock when this feed was fetched (used for the elapsed-time display). */
  fetchedAt?: number;
}

const ACTIVE = ["running", "waiting"];

function elapsed(session: LiveSession, now: number | undefined): string {
  const end = session.ended_at ? Date.parse(session.ended_at) : (now ?? Date.parse(session.started_at));
  const s = Math.max(0, Math.round((end - Date.parse(session.started_at)) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Live view. Demo/replay sessions are labelled DEMO; sessions fed by a real
 * platform connector (Zoom RTMS) are labelled as provider data, with their
 * connection state. Both use the same polling endpoint. */
export default function LivePage() {
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
  const active = ACTIVE.includes(feed?.session?.status ?? "");
  const isDemo = !feed?.session || feed.session.is_demo;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const f = await api.get<Feed>(`/meetings/${id}/live`);
        if (!cancelled) setFeed({ ...f, fetchedAt: Date.now() });
        if (!cancelled && ACTIVE.includes(f.session?.status ?? "")) timer = setTimeout(poll, 1000);
        else if (!cancelled && f.session) void reloadMeeting();
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
  }, [id, feed?.session?.id, active]);

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
      if (!feed.session.is_demo) {
        await api.post(`/meetings/${id}/external-source/live/stop`);
        setFeed(await api.get<Feed>(`/meetings/${id}/live`));
        return;
      }
      const session = await api.post<LiveSession>(`/live-sessions/${feed.session.id}/stop`);
      setFeed({ ...feed, session });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (!meeting) return <Spinner label={t.common.loading} />;
  const canStart = meeting.permissions.edit && meeting.entry_count === 0 && (!feed?.session || (feed.session.is_demo && !active));

  return (
    <>
      <MeetingHeader meeting={meeting} />
      {isDemo ? (
        <div className="mb-4 rounded-md border-2 border-dashed border-amber-400 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-900" role="status" data-testid="demo-banner">
          {t.live.banner}
        </div>
      ) : (
        <div className="mb-4 rounded-md border-2 border-emerald-500 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-900" role="status" data-testid="provider-banner">
          {t.liveProvider.banner} · {feed?.session?.connector}
        </div>
      )}
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
            {feed.session.is_demo ? <Badge tone="warning">DEMO · {feed.session.connector}</Badge> : <Badge tone="success">{feed.session.connector}</Badge>}
            <span className="text-sm">
              {t.live.status}: <b data-testid="replay-status">{feed.session.status}</b>
            </span>
            {feed.session.is_demo ? (
              <div className="min-w-48 flex-1">
                <ProgressBar value={feed.session.entries_emitted} max={feed.session.entries_total} label={t.live.emitted} />
              </div>
            ) : (
              <span className="flex flex-1 flex-wrap gap-3 text-xs text-muted">
                <span>
                  {t.liveProvider.duration}: {elapsed(feed.session, feed.fetchedAt)}
                </span>
                <span>
                  {t.live.emitted}: {feed.session.entries_emitted}
                </span>
                <span>
                  {t.liveProvider.reconnects}: {feed.session.reconnect_count ?? 0}
                </span>
                <span>
                  {t.liveProvider.lastEvent}: {formatDateTime(feed.session.last_event_at)}
                </span>
              </span>
            )}
            {(feed.session.is_demo ? running : active) && meeting.permissions.edit && (
              <Button variant="danger" onClick={() => void stop()}>
                {t.live.stop}
              </Button>
            )}
          </div>
          {feed.session.status === "waiting" && <Alert tone="info">{t.liveProvider.waiting}</Alert>}
          {feed.session.status === "interrupted" && <Alert tone="warning">{t.liveProvider.interrupted}</Alert>}
          {feed.session.status_message && !feed.session.is_demo && <p className="text-xs text-muted">{feed.session.status_message}</p>}
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
