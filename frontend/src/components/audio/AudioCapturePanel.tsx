"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Alert, Badge, Button, Card, Checkbox, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { SourceCapture, listMicrophones, openDisplayAudio, openMicrophone, unlockDeviceLabels, type SourceKind } from "@/lib/audio/capture";
import type { Utterance } from "@/lib/audio/segmenter";
import { encodeWav } from "@/lib/audio/wav";
import { errorMessage } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { AudioChunkResult, AudioSession, AudioSpeaker, LiveSession } from "@/lib/types";

interface PickedSource {
  id: string;
  kind: SourceKind;
  label: string;
  singleSpeaker: boolean;
  deviceId?: string;
  stream?: MediaStream; // system/tab audio is picked (and its permission granted) up front
}

interface SourceStats {
  level: number;
  queued: number;
  sent: number;
  errors: number;
  lastError: string | null;
}

const SAMPLE_RATE = 16000;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Readable messages for getUserMedia / getDisplayMedia failures. */
function mediaError(err: unknown): string {
  if (err instanceof DOMException) {
    if (err.name === "NotAllowedError" || err.name === "SecurityError") return t.audio.permissionDenied;
    if (err.name === "NotFoundError" || err.name === "OverconstrainedError") return t.audio.deviceMissing;
    if (err.name === "NotReadableError" || err.name === "AbortError") return t.audio.deviceBusy;
  }
  return errorMessage(err);
}

const noopSubscribe = () => () => undefined;
function supported(): boolean {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof AudioWorkletNode !== "undefined";
}

/**
 * Live capture from audio sources on this computer: microphones and the
 * system / tab audio of a meeting. Each source is segmented into utterances
 * in the browser and sent to the server, which recognises speech, separates
 * speakers and translates. The parent page shows the resulting live feed.
 */
export function AudioCapturePanel({ meetingId, session, onChanged }: { meetingId: string; session: LiveSession | null; onChanged: () => void }) {
  const [mics, setMics] = useState<MediaDeviceInfo[] | null>(null);
  const [picked, setPicked] = useState<PickedSource[]>([]);
  const [consent, setConsent] = useState(false);
  const [translate, setTranslate] = useState(true);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [stats, setStats] = useState<Record<string, SourceStats>>({});
  const [speakers, setSpeakers] = useState<AudioSpeaker[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const captures = useRef(new Map<string, SourceCapture>());
  const queues = useRef(new Map<string, Utterance[]>());
  const seqs = useRef(new Map<string, number>());
  const pumping = useRef(new Set<string>());
  const counters = useRef(new Map<string, SourceStats>());

  // Client-only capability check (server snapshot is optimistic to avoid a hydration mismatch).
  const isSupported = useSyncExternalStore(noopSubscribe, supported, () => true);
  const running = sessionId !== null;
  const orphan = !running && session?.connector === "audio_capture" && ["running", "waiting"].includes(session.status);

  // Meters and queue counters refresh a few times per second while capturing.
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      const next: Record<string, SourceStats> = {};
      for (const [id, c] of counters.current) {
        next[id] = { ...c, level: captures.current.get(id)?.level ?? 0, queued: queues.current.get(id)?.length ?? 0 };
      }
      setStats(next);
    }, 250);
    return () => clearInterval(timer);
  }, [running]);

  // Speaker list (with voice-reference status) while capturing.
  useEffect(() => {
    if (!sessionId) return;
    const timer = setInterval(() => {
      api.get<AudioSession>(`/audio-sessions/${sessionId}`).then(
        (s) => setSpeakers(s.speakers),
        () => undefined,
      );
    }, 3000);
    return () => clearInterval(timer);
  }, [sessionId]);

  // Leaving the page stops the capture.
  useEffect(() => {
    if (!running) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = t.audio.leaveWarning;
    };
    window.addEventListener("beforeunload", warn);
    const caps = captures.current;
    const sid = sessionId;
    return () => {
      window.removeEventListener("beforeunload", warn);
      if (caps.size) {
        caps.forEach((c) => void c.stop());
        caps.clear();
        void api.post(`/audio-sessions/${sid}/stop`).catch(() => undefined);
      }
    };
  }, [running, sessionId]);

  if (!isSupported) return <Alert tone="warning">{t.audio.browserUnsupported}</Alert>;

  async function loadMics() {
    setError(null);
    try {
      await unlockDeviceLabels();
      setMics(await listMicrophones());
    } catch (err) {
      setError(mediaError(err));
    }
  }

  function toggleMic(d: MediaDeviceInfo, on: boolean) {
    const id = `mic-${picked.filter((p) => p.kind === "microphone").length + 1}-${d.deviceId.slice(0, 8).toLowerCase().replace(/[^a-z0-9]/g, "")}`;
    if (on) {
      const first = !picked.some((p) => p.kind === "microphone");
      setPicked([...picked, { id: id.slice(0, 32), kind: "microphone", label: first ? t.audio.me : d.label || "Micro", singleSpeaker: true, deviceId: d.deviceId }]);
    } else {
      setPicked(picked.filter((p) => p.deviceId !== d.deviceId));
    }
  }

  async function addSystem() {
    setError(null);
    try {
      const stream = await openDisplayAudio();
      const n = picked.filter((p) => p.kind === "system").length + 1;
      setPicked([...picked, { id: `meeting-${n}`, kind: "system", label: n > 1 ? `${t.audio.systemSource} ${n}` : t.audio.systemSource, singleSpeaker: false, stream }]);
    } catch (err) {
      if (err instanceof Error && err.message === "NO_AUDIO_TRACK") setError(t.audio.noAudioTrack);
      else if (!(err instanceof DOMException && err.name === "NotAllowedError")) setError(mediaError(err));
    }
  }

  function update(id: string, patch: Partial<PickedSource>) {
    setPicked(picked.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  }

  function remove(id: string) {
    picked.find((p) => p.id === id)?.stream?.getTracks().forEach((tr) => tr.stop());
    setPicked(picked.filter((p) => p.id !== id));
  }

  async function send(sid: string, sourceId: string, u: Utterance): Promise<void> {
    const seq = seqs.current.get(sourceId) ?? 0;
    seqs.current.set(sourceId, seq + 1);
    const c = counters.current.get(sourceId)!;
    for (let attempt = 0; attempt < 4; attempt++) {
      const fd = new FormData();
      fd.append("source_id", sourceId);
      fd.append("chunk_seq", String(seq));
      fd.append("offset_ms", String(u.startMs));
      fd.append("file", new Blob([encodeWav(u.samples, SAMPLE_RATE)], { type: "audio/wav" }), "chunk.wav");
      try {
        const r = await api.post<AudioChunkResult>(`/audio-sessions/${sid}/chunks`, fd);
        c.sent += 1;
        c.lastError = null;
        if (r.note) setNote(r.note);
        return;
      } catch (err) {
        const retryAfter = err instanceof ApiError ? Number(err.details?.retry_after_seconds ?? 0) : 0;
        const retryable = err instanceof ApiError && (err.status === 429 || err.details?.retryable === true || err.status === 0);
        if (!retryable || attempt === 3) {
          c.errors += 1;
          c.lastError = errorMessage(err);
          return;
        }
        await sleep(retryAfter > 0 ? retryAfter * 1000 : 1500 * (attempt + 1));
      }
    }
  }

  async function pump(sid: string, sourceId: string) {
    if (pumping.current.has(sourceId)) return;
    pumping.current.add(sourceId);
    try {
      const q = queues.current.get(sourceId) ?? [];
      while (q.length) await send(sid, sourceId, q.shift()!);
    } finally {
      pumping.current.delete(sourceId);
    }
  }

  async function start() {
    if (!picked.length) return setError(t.audio.needSource);
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const res = await api.post<AudioSession>(`/meetings/${meetingId}/audio-sessions`, {
        sources: picked.map((p) => ({ id: p.id, kind: p.kind, label: p.label.trim() || p.id, single_speaker: p.singleSpeaker })),
        translate,
        consent_confirmed: consent,
      });
      const sid = res.session.id;
      const t0 = performance.now();
      for (const p of picked) {
        const stream = p.stream ?? (await openMicrophone(p.deviceId!));
        queues.current.set(p.id, []);
        seqs.current.set(p.id, 0);
        counters.current.set(p.id, { level: 0, queued: 0, sent: 0, errors: 0, lastError: null });
        const cap = new SourceCapture(stream, (u) => {
          queues.current.get(p.id)?.push(u);
          void pump(sid, p.id);
        });
        await cap.start(t0);
        captures.current.set(p.id, cap);
      }
      setSessionId(sid);
      setSpeakers(res.speakers);
      onChanged();
    } catch (err) {
      captures.current.forEach((c) => void c.stop());
      captures.current.clear();
      setError(mediaError(err));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!sessionId) return;
    setBusy(true);
    const sid = sessionId;
    try {
      await Promise.all([...captures.current.values()].map((c) => c.stop()));
      captures.current.clear();
      for (const id of queues.current.keys()) void pump(sid, id);
      for (let i = 0; i < 120 && (pumping.current.size || [...queues.current.values()].some((q) => q.length)); i++) await sleep(250);
      const res = await api.post<AudioSession>(`/audio-sessions/${sid}/stop`);
      setSpeakers(res.speakers);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSessionId(null);
      setPicked([]);
      setBusy(false);
      onChanged();
    }
  }

  async function endOrphan() {
    if (!session) return;
    try {
      await api.post(`/audio-sessions/${session.id}/stop`);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function rename(key: string) {
    const sid = sessionId ?? session?.id;
    const name = names[key]?.trim();
    if (!sid || !name) return;
    try {
      const sp = await api.patch<AudioSpeaker>(`/audio-sessions/${sid}/speakers/${key}`, { display_name: name });
      setSpeakers(speakers.map((s) => (s.speaker_key === key ? sp : s)));
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const lagging = Object.values(stats).some((s) => s.queued >= 3);

  return (
    <Card title={t.audio.title} className="mb-4">
      <div className="space-y-4 text-sm" data-testid="audio-capture">
        <p className="text-muted">{t.audio.intro}</p>
        {error && <Alert tone="danger">{error}</Alert>}
        {note && <Alert tone="warning">{note}</Alert>}
        {orphan && (
          <Alert tone="warning">
            {t.audio.orphan}{" "}
            <Button size="sm" onClick={() => void endOrphan()}>
              {t.audio.endOrphan}
            </Button>
          </Alert>
        )}

        {!running && !orphan && (
          <>
            <section>
              <h3 className="mb-1 font-medium">{t.audio.meetingAudio}</h3>
              <Button size="sm" onClick={() => void addSystem()} data-testid="add-system-audio">
                {t.audio.addSystem}
              </Button>
              <p className="mt-1 text-xs text-muted">{t.audio.systemHelp}</p>
            </section>

            <section>
              <h3 className="mb-1 font-medium">{t.audio.microphones}</h3>
              {mics === null ? (
                <Button size="sm" onClick={() => void loadMics()} data-testid="unlock-mics">
                  {t.audio.unlock}
                </Button>
              ) : mics.length === 0 ? (
                <p className="text-xs text-muted">{t.audio.noMics}</p>
              ) : (
                <ul className="space-y-1" data-testid="mic-list">
                  {mics.map((d) => (
                    <li key={d.deviceId}>
                      <Checkbox label={d.label || d.deviceId} checked={picked.some((p) => p.deviceId === d.deviceId)} onChange={(e) => toggleMic(d, e.target.checked)} />
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-1 text-xs text-muted">{t.audio.echoTip}</p>
            </section>

            {picked.length > 0 && (
              <ul className="divide-y divide-line rounded border border-line" data-testid="picked-sources">
                {picked.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center gap-2 p-2">
                    <Badge tone={p.kind === "microphone" ? "info" : "brand"}>{p.kind === "microphone" ? "MIC" : "MEETING"}</Badge>
                    <Input className="w-48" aria-label={t.audio.labelFor} value={p.label} maxLength={80} onChange={(e) => update(p.id, { label: e.target.value })} />
                    <Checkbox label={t.audio.singleSpeaker} checked={p.singleSpeaker} onChange={(e) => update(p.id, { singleSpeaker: e.target.checked })} />
                    <Button size="sm" variant="ghost" onClick={() => remove(p.id)}>
                      {t.audio.remove}
                    </Button>
                  </li>
                ))}
              </ul>
            )}

            <div className="space-y-2">
              <Checkbox label={t.audio.translate} checked={translate} onChange={(e) => setTranslate(e.target.checked)} />
              <Checkbox label={t.audio.consent} checked={consent} onChange={(e) => setConsent(e.target.checked)} data-testid="audio-consent" />
            </div>
            <Button variant="primary" onClick={() => void start()} loading={busy} disabled={!consent || picked.length === 0} data-testid="start-audio">
              {t.audio.start}
            </Button>
          </>
        )}

        {running && (
          <>
            <ul className="space-y-2" data-testid="audio-sources-live">
              {picked.map((p) => {
                const s = stats[p.id];
                return (
                  <li key={p.id} className="flex flex-wrap items-center gap-3">
                    <span className="w-40 truncate font-medium">{p.label}</span>
                    <span className="h-2 w-40 overflow-hidden rounded bg-gray-200" aria-label={t.audio.level}>
                      <span className="block h-full bg-emerald-500 transition-[width]" style={{ width: `${Math.min(100, Math.round((s?.level ?? 0) * 400))}%` }} />
                    </span>
                    <span className="text-xs text-muted">
                      {t.audio.sent}: <b data-testid={`sent-${p.id}`}>{s?.sent ?? 0}</b> · {t.audio.queued}: {s?.queued ?? 0}
                      {s?.errors ? ` · ${t.audio.errors}: ${s.errors}` : ""}
                    </span>
                    {s?.lastError && <span className="text-xs text-red-700">{s.lastError}</span>}
                  </li>
                );
              })}
            </ul>
            {lagging && <Alert tone="warning">{t.audio.lag}</Alert>}
            <Button variant="danger" onClick={() => void stop()} loading={busy} data-testid="stop-audio">
              {t.audio.stop}
            </Button>
          </>
        )}

        {(running || speakers.length > 0) && (
          <section data-testid="audio-speakers">
            <h3 className="mb-1 font-medium">{t.audio.speakers}</h3>
            {speakers.length === 0 ? (
              <p className="text-xs text-muted">{t.audio.noSpeakers}</p>
            ) : (
              <ul className="space-y-1">
                {speakers.map((s) => (
                  <li key={s.speaker_key} className="flex flex-wrap items-center gap-2">
                    <Badge>{s.speaker_key}</Badge>
                    <Input
                      className="w-48"
                      aria-label={`${t.audio.rename} ${s.speaker_key}`}
                      value={names[s.speaker_key] ?? s.display_name}
                      maxLength={200}
                      onChange={(e) => setNames({ ...names, [s.speaker_key]: e.target.value })}
                    />
                    <Button size="sm" onClick={() => void rename(s.speaker_key)} disabled={!names[s.speaker_key] || names[s.speaker_key] === s.display_name}>
                      {t.audio.save}
                    </Button>
                    <span className="text-xs text-muted">{s.segments}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-1 text-xs text-muted">{t.audio.unattributed}</p>
          </section>
        )}
      </div>
    </Card>
  );
}
