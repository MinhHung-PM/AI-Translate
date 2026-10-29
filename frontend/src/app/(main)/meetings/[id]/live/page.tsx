"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AudioCapturePanel } from "@/components/audio/AudioCapturePanel";
import { CAPTION_SIZE, LiveCaptionFeed, type CaptionPrefs, type InterimCaption } from "@/components/audio/LiveCaptionFeed";
import { Alert, Badge, Button, Checkbox, EmptyState, Field, Fred, Input, ProgressBar, Spinner, Tabs, Textarea, cn } from "@/components/ui";
import { TranscriptTable } from "@/components/meeting/transcript-table";
import { useMeeting } from "@/components/meeting/use-meeting";
import { api } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useFeature } from "@/lib/session";
import { setFocusMode } from "@/lib/prefs";
import type { Language, LiveSession, TranscriptEntry } from "@/lib/types";

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

/** Small square toolbar button in the live status bar. */
function BarButton({ on, onClick, children, label }: { on?: boolean; onClick: () => void; children: React.ReactNode; label?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={on}
      className={cn("rounded-lg border border-line px-2 py-1 whitespace-nowrap", on ? "bg-ink text-bg" : "bg-transparent hover:bg-surface-2")}
    >
      {children}
    </button>
  );
}

/** Live view, in three states: setup → running (focus layout, captions fill the screen) → ended.
 * Sources: live audio capture from this computer (speech-to-text with speaker separation), a real
 * platform connector (Zoom RTMS), or the replay demo (labelled DEMO). All feed the same polling endpoint. */
export default function LivePage() {
  const replayDemo = useFeature("replay_demo");
  const router = useRouter();
  const { id, data: meeting, reload: reloadMeeting } = useMeeting();
  const [memoBusy, setMemoBusy] = useState(false);
  const [feed, setFeed] = useState<Feed | null>(null);
  const [text, setText] = useState("");
  const [interval, setIntervalSec] = useState("1.5");
  const [translate, setTranslate] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"audio" | "replay">("audio");
  const [refresh, setRefresh] = useState(0);
  const [interim, setInterim] = useState<Record<string, InterimCaption>>({});
  const [view, setView] = useState<"bubbles" | "table">("bubbles");
  const [prefs, setPrefs] = useState<CaptionPrefs>({ size: CAPTION_SIZE.initial, follow: true, onlyTranslation: false });
  // Capture running in this browser (from the audio panel), the 600px side-by-side preview,
  // and "record more" after a finished session.
  const [capturing, setCapturing] = useState(false);
  const [preview, setPreview] = useState(false);
  const [resume, setResume] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const running = feed?.session?.status === "running";
  const active = ACTIVE.includes(feed?.session?.status ?? "");
  const isAudio = feed?.session?.connector === "audio_capture";
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
  }, [id, feed?.session?.id, active, refresh]);

  // Focus mode: the sidebar steps aside while captions run.
  const focus = capturing || (!!feed?.session && !isAudio && active);
  useEffect(() => {
    setFocusMode(focus);
  }, [focus]);
  useEffect(() => () => setFocusMode(false), []);

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

  async function generateMemo() {
    setMemoBusy(true);
    setError(null);
    try {
      await api.post(`/meetings/${id}/memo/generate`);
      router.push(`/meetings/${id}/memo`);
    } catch (err) {
      setError(errorMessage(err));
      setMemoBusy(false);
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

  if (!meeting) {
    return (
      <div className="p-8">
        <Spinner label={t.common.loading} />
      </div>
    );
  }
  const canStart = meeting.permissions.edit && meeting.entry_count === 0 && (!feed?.session || (feed.session.is_demo && !active));
  const audioMode = meeting.permissions.edit && (mode === "audio" || (isAudio && active));
  const showTabs = meeting.permissions.edit && !active && !capturing;
  const finished = !!feed?.session && !active && !capturing && meeting.entry_count > 0;
  const ended = finished && !resume;
  const entries = feed?.entries ?? [];
  const speakerCount = new Set(entries.map((e) => e.speaker_label).filter(Boolean)).size;
  const selfLabels = (feed?.session?.capture_config?.sources ?? []).filter((s) => s.kind === "microphone").map((s) => s.label);
  const phase = capturing || active ? "running" : ended ? "ended" : "setup";
  // Honest labels: simulated data is always marked (real audio capture needs no banner).
  const banner = isAudio && isDemo ? "mock" : isAudio || (audioMode && !feed?.session) ? null : isDemo ? "demo" : "provider";

  const toolbar = (
    <>
      <BarButton onClick={() => setPrefs({ ...prefs, size: Math.max(CAPTION_SIZE.min, prefs.size - CAPTION_SIZE.step) })} label={t.captions.smaller}>
        A−
      </BarButton>
      <BarButton onClick={() => setPrefs({ ...prefs, size: Math.min(CAPTION_SIZE.max, prefs.size + CAPTION_SIZE.step) })} label={t.captions.larger}>
        A+
      </BarButton>
      <BarButton on={prefs.follow} onClick={() => setPrefs({ ...prefs, follow: !prefs.follow })}>
        {t.captions.follow}
      </BarButton>
      <BarButton on={prefs.onlyTranslation} onClick={() => setPrefs({ ...prefs, onlyTranslation: !prefs.onlyTranslation })}>
        {t.captions.onlyTranslation}
      </BarButton>
      <Tabs
        size="sm"
        value={view}
        onChange={setView}
        className="rounded-lg"
        items={[
          { value: "bubbles", label: t.captions.bubbles },
          { value: "table", label: t.captions.table },
        ]}
      />
    </>
  );

  const captions =
    view === "bubbles" ? (
      <LiveCaptionFeed entries={isAudio ? entries : []} interim={Object.values(interim)} selfLabels={selfLabels} prefs={prefs} />
    ) : (
      <div className="min-h-0 flex-1 overflow-y-auto px-[clamp(14px,2.4vw,32px)] py-5">
        {entries.length === 0 ? <EmptyState fred="listening" title={t.live.waiting} /> : <TranscriptTable entries={entries} target={meeting.target_language} editable={false} />}
      </div>
    );

  const steps = [
    { key: "setup", label: t.liveSteps.setup },
    { key: "running", label: t.liveSteps.running },
    { key: "ended", label: t.liveSteps.ended },
  ] as const;

  return (
    <div className={cn("flex flex-1 justify-center", preview && "bg-nav")}>
      <div className={cn("@container flex min-w-0 flex-1 flex-col bg-bg", preview && "max-w-[600px] border-x border-line", phase === "running" ? "h-[100dvh]" : "min-h-[100dvh]")}>
        <header className="sticky top-0 z-[4] flex flex-wrap items-center gap-x-3.5 gap-y-2 border-b border-line bg-bg px-[clamp(14px,2.4vw,28px)] py-3">
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="eyebrow truncate text-muted">
              <Link href={`/projects/${meeting.project_id}`}>{meeting.project_name}</Link> · {t.liveTranslate.eyebrow}
            </span>
            <h1 className="truncate text-[15px] font-semibold">{meeting.title}</h1>
          </div>
          {isAudio && isDemo && <Badge tone="warning">MOCK</Badge>}
          {feed?.session?.is_demo && !isAudio && <Badge tone="warning">DEMO</Badge>}
          {feed?.session && !feed.session.is_demo && !isAudio && <Badge tone="success">{feed.session.connector}</Badge>}
          <ol className="hidden rounded-full border border-line p-0.5 text-xs @min-[700px]:flex" aria-label={t.liveSteps.label}>
            {steps.map((s) => (
              <li key={s.key} aria-current={phase === s.key ? "step" : undefined} className={cn("rounded-full px-2.5 py-1 whitespace-nowrap", phase === s.key ? "bg-ink text-bg" : "text-muted")}>
                {s.label}
              </li>
            ))}
          </ol>
          <span className="hidden items-center gap-1 text-xs @min-[860px]:flex">
            <Link href={`/meetings/${id}`} className="rounded-full px-2 py-1 text-muted hover:text-ink">
              {t.workspace.tabs.transcript}
            </Link>
            <Link href={`/meetings/${id}/memo`} className="rounded-full px-2 py-1 text-muted hover:text-ink">
              {t.workspace.tabs.memo}
            </Link>
          </span>
          <button
            type="button"
            onClick={() => setPreview(!preview)}
            title={t.liveTranslate.previewHint}
            className="rounded-full border border-line px-2.5 py-1 text-xs whitespace-nowrap hover:bg-surface-2"
          >
            {preview ? t.liveTranslate.fullWidth : t.liveTranslate.preview600}
          </button>
        </header>

        {banner === "mock" && (
          <div className="border-b border-line bg-warning-soft px-[clamp(14px,2.4vw,28px)] py-2 text-xs" role="status" data-testid="audio-banner">
            <b className="font-mono text-warning">MOCK</b> · {t.audio.mockBanner}
            <span className="block text-muted">{t.audio.mockHint}</span>
          </div>
        )}
        {banner === "demo" && (
          <div className="border-b border-line bg-warning-soft px-[clamp(14px,2.4vw,28px)] py-2 text-xs" role="status" data-testid="demo-banner">
            <b className="font-mono text-warning">DEMO</b> · {t.live.banner}
          </div>
        )}
        {banner === "provider" && (
          <div className="border-b border-line bg-success-soft px-[clamp(14px,2.4vw,28px)] py-2 text-xs" role="status" data-testid="provider-banner">
            {t.liveProvider.banner} · {feed?.session?.connector}
          </div>
        )}
        {feed?.session && (
          <span className="sr-only" data-testid="replay-status">
            {feed.session.status}
          </span>
        )}
        {error && (
          <div className="px-[clamp(14px,2.4vw,28px)] pt-3">
            <Alert tone="danger" fred="sad">
              {error}
            </Alert>
          </div>
        )}

        {ended && (
          <div className="flex flex-1 flex-col items-center justify-center gap-6 px-5 py-8">
            <div className="flex w-full max-w-[760px] flex-wrap items-center gap-6 rounded-[22px] border border-line bg-surface p-[clamp(20px,3vw,36px)]" data-testid="live-finished">
              <Fred pose="happy" alt={t.fred.happyAlt} className="h-[180px] w-auto" />
              <div className="flex min-w-60 flex-1 flex-col gap-3">
                <span className="eyebrow text-[11px] tracking-[.08em] text-success">{t.liveDone.eyebrow}</span>
                <h2 className="font-display text-2xl leading-tight font-semibold">{t.liveDone.title}</h2>
                <dl className="grid grid-cols-3 gap-2.5">
                  {[
                    [feed?.session ? elapsed(feed.session, feed.fetchedAt) : "—", t.liveDone.duration],
                    [String(meeting.entry_count), t.liveDone.lines],
                    [speakerCount ? String(speakerCount) : "—", t.liveDone.speakers],
                  ].map(([v, k]) => (
                    <div key={k} className="flex flex-col-reverse gap-0.5">
                      <dt className="text-xs text-muted">{k}</dt>
                      <dd className="font-display text-xl font-semibold">{v}</dd>
                    </div>
                  ))}
                </dl>
                <div className="mt-1 flex flex-wrap gap-2.5">
                  {meeting.permissions.edit &&
                    (meeting.memo_status ? (
                      <Link href={`/meetings/${id}/memo`}>
                        <Button variant="primary" data-testid="live-open-memo">
                          {t.liveDone.openMemo}
                        </Button>
                      </Link>
                    ) : (
                      <Button variant="primary" onClick={() => void generateMemo()} loading={memoBusy} data-testid="live-generate-memo">
                        {t.liveDone.generateMemo}
                      </Button>
                    ))}
                  <Link href={`/meetings/${id}`}>
                    <Button>{t.liveDone.openTranscript}</Button>
                  </Link>
                  {audioMode && (
                    <Button variant="ghost" onClick={() => setResume(true)} data-testid="live-resume">
                      {t.liveDone.recordMore}
                    </Button>
                  )}
                </div>
                <p className="text-xs leading-normal text-muted">{t.liveDone.hint}</p>
              </div>
            </div>
            {/* Replay / platform sessions: the streamed lines stay on screen for a quick check. */}
            {!isAudio && entries.length > 0 && (
              <div className="w-full max-w-[1100px]">
                <TranscriptTable entries={entries} target={meeting.target_language} editable={false} />
              </div>
            )}
          </div>
        )}

        {!ended && showTabs && replayDemo && (
          <div className="px-[clamp(14px,2.4vw,28px)] pt-4">
            <Tabs
              value={mode}
              onChange={setMode}
              items={[
                { value: "audio", label: t.audio.tab },
                { value: "replay", label: t.audio.replayTab },
              ]}
            />
          </div>
        )}

        {/* Kept mounted after a session so its speaker list survives "record more". */}
        {audioMode && (
          <div className={cn("flex min-h-0 flex-1 flex-col", ended && "hidden")}>
            <AudioCapturePanel
              meetingId={id}
              session={feed?.session ?? null}
              defaultLanguages={[...new Set([meeting.source_language, meeting.target_language].filter((x): x is Language => !!x))]}
              onChanged={() => setRefresh((n) => n + 1)}
              onRunningChange={(r) => {
                setCapturing(r);
                if (r) setResume(false);
              }}
              onInterim={(sourceId, label, text, translation) =>
                setInterim((prev) => {
                  const next = { ...prev };
                  if (text || translation) next[sourceId] = { sourceId, label, text, translation };
                  else delete next[sourceId];
                  return next;
                })
              }
              captions={captions}
              toolbar={toolbar}
              lineCount={feed?.session?.entries_emitted ?? entries.length}
            />
          </div>
        )}

        {!ended && canStart && !audioMode && (
          <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-5 p-[clamp(16px,3vw,36px)]">
            <div className="flex flex-col gap-1.5">
              <span className="eyebrow text-[11px] tracking-[.08em] text-accent-text">DEMO</span>
              <h2 className="font-display text-[clamp(20px,2.4vw,26px)] font-semibold">{t.live.start}</h2>
            </div>
            <div className="grid gap-3 rounded-[14px] border border-line bg-surface p-4 md:grid-cols-3">
              <Field label={t.workspace.chooseFile}>
                {(fid) => <input id={fid} ref={fileRef} type="file" accept=".txt,.srt,.vtt,.json" className="text-sm file:mr-3 file:rounded-full file:border file:border-line-strong file:bg-transparent file:px-3 file:py-1 file:text-ink" />}
              </Field>
              <Field label={t.live.interval}>
                {(fid) => <Input id={fid} type="number" min={0} max={10} step={0.5} value={interval} onChange={(e) => setIntervalSec(e.target.value)} />}
              </Field>
              <div className="flex items-end pb-2">
                <Checkbox label={t.live.translate} checked={translate} onChange={(e) => setTranslate(e.target.checked)} />
              </div>
              <Field label={t.workspace.pasteText} className="md:col-span-3">
                {(fid) => <Textarea id={fid} rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder={t.workspace.pastePlaceholder} />}
              </Field>
            </div>
            <div>
              <Button variant="primary" size="lg" onClick={() => void start()} loading={busy} data-testid="start-replay">
                {t.live.start}
              </Button>
            </div>
          </div>
        )}
        {!ended && !canStart && !audioMode && !feed?.session && meeting.entry_count > 0 && (
          <div className="p-[clamp(16px,3vw,36px)]">
            <Alert tone="info">{t.live.requiresEmpty}</Alert>
          </div>
        )}

        {/* Replay demo and platform connectors (audio capture renders its own running layout). */}
        {!ended && feed?.session && !isAudio && (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-[clamp(14px,2.4vw,28px)] py-2 text-xs">
              {running && (
                <span className="flex items-center gap-1.5 font-mono font-medium text-danger">
                  <span className="size-2 animate-rec rounded-full bg-danger" aria-hidden />
                  {elapsed(feed.session, feed.fetchedAt)}
                </span>
              )}
              <span className="text-muted">
                {t.live.status}: <b className="font-medium text-ink">{t.live.statuses[feed.session.status]}</b>
              </span>
              {feed.session.is_demo ? (
                <div className="min-w-48 flex-1">
                  <ProgressBar value={feed.session.entries_emitted} max={feed.session.entries_total} label={t.live.emitted} tone="accent" />
                </div>
              ) : (
                <span className="flex flex-1 flex-wrap gap-3 text-muted">
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
              <div className="flex flex-wrap items-center gap-1">
                {toolbar}
                {(feed.session.is_demo ? running : active) && meeting.permissions.edit && (
                  <button type="button" onClick={() => void stop()} className="ml-1 rounded-lg bg-ink px-3 py-1 font-semibold text-bg">
                    {t.live.stop}
                  </button>
                )}
              </div>
            </div>
            {(feed.session.status === "waiting" || feed.session.status === "interrupted" || (feed.session.status_message && !feed.session.is_demo)) && (
              <div className="flex flex-col gap-2 px-[clamp(14px,2.4vw,28px)] pt-2.5">
                {feed.session.status === "waiting" && <Alert tone="info">{t.liveProvider.waiting}</Alert>}
                {feed.session.status === "interrupted" && (
                  <Alert tone="warning" fred="sad">
                    {t.liveProvider.interrupted}
                  </Alert>
                )}
                {feed.session.status_message && !feed.session.is_demo && (
                  <p className="text-xs text-muted" data-testid="live-status-message">
                    {feed.session.status_message}
                  </p>
                )}
              </div>
            )}
            {/* Replay lines arrive whole: the bilingual table is the natural view; bubbles show them too. */}
            {view === "bubbles" ? (
              <LiveCaptionFeed entries={entries} interim={[]} selfLabels={[]} prefs={prefs} />
            ) : (
              captions
            )}
          </div>
        )}
      </div>
    </div>
  );
}
