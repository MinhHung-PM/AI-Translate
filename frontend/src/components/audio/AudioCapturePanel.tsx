"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Alert, Badge, Button, Card, Checkbox, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { RealtimeCaptionSource, type CaptionState, type RealtimeToken } from "@/lib/audio/realtime";
import { SonioxCaptionSource } from "@/lib/audio/soniox";
import type { FinalUtterance } from "@/lib/audio/realtime-events";
import { denoise, type DenoisedSource, type NoiseLevel } from "@/lib/audio/denoise";
import { SourceCapture, listMicrophones, openDisplayAudio, openMicrophone, unlockDeviceLabels, type SourceKind } from "@/lib/audio/capture";
import type { Utterance } from "@/lib/audio/segmenter";
import { encodeWav } from "@/lib/audio/wav";
import { errorMessage } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { AudioChunkResult, AudioSession, AudioSpeaker, Language, LiveSession, ProviderConfig } from "@/lib/types";

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
  echoes: number;
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
  // Connection errors from OpenAI / Soniox carry a useful message (e.g. a rejected key).
  if (!(err instanceof ApiError) && err instanceof Error && err.message) return `${t.common.errorGeneric} (${err.message})`;
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
const ALL_LANGS: Language[] = ["ja", "vi", "en"];

export function AudioCapturePanel({
  meetingId,
  session,
  defaultLanguages,
  onChanged,
  onInterim,
}: {
  meetingId: string;
  session: LiveSession | null;
  defaultLanguages: Language[];
  onChanged: () => void;
  /** When given, words being spoken are reported to the parent (shown in the caption feed) instead of here. */
  onInterim?: (sourceId: string, label: string, text: string, translation?: string) => void;
}) {
  const [mics, setMics] = useState<MediaDeviceInfo[] | null>(null);
  const [picked, setPicked] = useState<PickedSource[]>([]);
  const [consent, setConsent] = useState(false);
  const [translate, setTranslate] = useState(true);
  // auto = the speech model detects the language itself (mixed-language speech too).
  const [langMode, setLangMode] = useState<"auto" | "listed">("auto");
  const [langs, setLangs] = useState<Language[]>(defaultLanguages.length ? defaultLanguages : ALL_LANGS);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [stats, setStats] = useState<Record<string, SourceStats>>({});
  const [speakers, setSpeakers] = useState<AudioSpeaker[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // Streaming captions: words appear while speaking (OpenAI Realtime). Off = one request per sentence.
  const [streamingWanted, setStreamingWanted] = useState(true);
  const [noise, setNoise] = useState<NoiseLevel>("standard");
  // interpret = OpenAI live interpretation (translated words stream in); the rest are caption modes.
  const [latency, setLatency] = useState<"interpret" | "fast" | "balanced" | "accurate">("interpret");
  const [playVoice, setPlayVoice] = useState(false);
  // Live speech provider: OpenAI Realtime (WebRTC) or Soniox (WebSocket; key added in AI Settings).
  const [sttProvider, setSttProvider] = useState<"openai" | "soniox">("openai");
  const providerConfigs = useApi<ProviderConfig[]>("/providers/configs");
  const sonioxReady = !!providerConfigs.data?.some((c) => c.provider === "soniox" && c.has_usable_key);
  const soniox = streamingWanted && sttProvider === "soniox";
  const voices = useRef(new Map<string, HTMLAudioElement>());
  const [gates, setGates] = useState<Record<string, boolean>>({});
  const [interim, setInterim] = useState<Record<string, { text: string; translation?: string }>>({});
  const [conn, setConn] = useState<Record<string, CaptionState>>({});

  const captures = useRef(new Map<string, SourceCapture>());
  const queues = useRef(new Map<string, Utterance[]>());
  const seqs = useRef(new Map<string, number>());
  const pumping = useRef(new Set<string>());
  const counters = useRef(new Map<string, SourceStats>());
  const realtime = useRef(new Map<string, RealtimeCaptionSource | SonioxCaptionSource>());
  const cleaners = useRef(new Map<string, DenoisedSource>());
  const finals = useRef(new Map<string, Promise<void>>());
  // Set when the panel unmounts, so a start() still in progress tears itself down.
  const unmounted = useRef(false);
  useEffect(() => {
    unmounted.current = false;
    return () => {
      unmounted.current = true;
    };
  }, []);

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
      const g: Record<string, boolean> = {};
      for (const [id, d] of cleaners.current) g[id] = d.gateOpen();
      setGates(g);
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
    const rts = realtime.current;
    const cls = cleaners.current;
    const sid = sessionId;
    const fins = finals.current;
    const pumps = pumping.current;
    return () => {
      window.removeEventListener("beforeunload", warn);
      // Leaving the page: finish the last sentences first, then end the server session
      // (segments arriving after /stop would be refused and lost).
      const live = [...rts.values()];
      const capList = [...caps.values()];
      const cleanerList = [...cls.values()];
      rts.clear();
      caps.clear();
      cls.clear();
      if (!capList.length && !live.length) return; // already stopped with the Stop button
      void (async () => {
        await Promise.all(live.map((r) => r.stop().catch(() => undefined)));
        await Promise.all(capList.map((c) => c.stop().catch(() => undefined)));
        await Promise.race([Promise.all([...fins.values()]), sleep(10000)]);
        for (let i = 0; i < 40 && pumps.size; i++) await sleep(250);
        await Promise.all(cleanerList.map((d) => d.close().catch(() => undefined)));
        await api.post(`/audio-sessions/${sid}/stop`).catch(() => undefined);
      })();
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
      // "Stop sharing" in the browser bar ends the track: tell the user instead of capturing silence.
      stream.getAudioTracks()[0]?.addEventListener("ended", () => setError(t.audio.shareEnded));
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
        c.echoes += r.echoes ?? 0;
        c.lastError = null;
        if (r.note) setNote(r.note);
        if (r.entries.length) onChanged(); // refresh the live feed now instead of at the next poll
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

  function postFinal(sid: string, sourceId: string, u: FinalUtterance, model: string) {
    const c = counters.current.get(sourceId);
    const prev = finals.current.get(sourceId) ?? Promise.resolve();
    const next = prev.then(async () => {
      // Idempotent per item on the server, so a retry after a network blip never duplicates.
      for (let attempt = 0; attempt < 4; attempt++) {
        try {
          const r = await api.post<AudioChunkResult>(`/audio-sessions/${sid}/segments`, {
            source_id: sourceId,
            item_id: u.itemId.replace(/[^A-Za-z0-9_\-:.]/g, "_").slice(0, 120),
            text: u.text.slice(0, 5000),
            offset_ms: u.startMs,
            duration_ms: u.durationMs,
            model: model || null,
            speaker: u.speaker,
            translated_text: u.translation ? u.translation.slice(0, 8000) : null,
          });
          if (c) {
            c.sent += 1;
            c.echoes += r.echoes ?? 0;
            c.lastError = null;
          }
          if (r.note) setNote(r.note);
          if (r.entries.length) onChanged();
          return;
        } catch (err) {
          const retryAfter = err instanceof ApiError ? Number(err.details?.retry_after_seconds ?? 0) : 0;
          const retryable = err instanceof ApiError && (err.status === 429 || err.status === 0 || err.details?.retryable === true);
          if (!retryable || attempt === 3) {
            if (c) {
              c.errors += 1;
              c.lastError = errorMessage(err);
            }
            return;
          }
          await sleep(retryAfter > 0 ? retryAfter * 1000 : 1500 * (attempt + 1));
        }
      }
    });
    finals.current.set(sourceId, next);
  }

  async function startStreaming(sid: string, p: PickedSource, stream: MediaStream, cap: SourceCapture, t0: number, provider: string) {
    const getToken = () => api.post<RealtimeToken>(`/audio-sessions/${sid}/realtime-token`, { source_id: p.id });
    let rt: RealtimeCaptionSource | SonioxCaptionSource | null = null;
    const handlers = {
      onInterim: (_itemId: string, text: string, translation?: string) => {
        setInterim((prev) => ({ ...prev, [p.id]: { text, translation } }));
        onInterim?.(p.id, p.label, text, translation);
      },
      onFinal: (u: FinalUtterance) => postFinal(sid, p.id, u, rt?.model ?? ""),
      onError: (msg: string) => {
        const c = counters.current.get(p.id);
        if (c) {
          c.errors += 1;
          c.lastError = msg;
        }
      },
    };
    const clock = () => performance.now() - t0;
    const onState = (state: CaptionState) => setConn((prev) => ({ ...prev, [p.id]: state }));
    rt =
      provider === "soniox"
        ? new SonioxCaptionSource(cap, getToken, handlers, clock, onState, latency === "interpret")
        : new RealtimeCaptionSource(stream, getToken, handlers, clock, onState);
    if (playVoice) {
      rt.onRemoteAudio = (remote) => {
        const el = voices.current.get(p.id) ?? new Audio();
        el.srcObject = remote;
        voices.current.set(p.id, el);
        void el.play().catch(() => undefined);
      };
    }
    realtime.current.set(p.id, rt);
    await rt.start();
  }

  async function start() {
    if (!picked.length) return setError(t.audio.needSource);
    if (busy) return; // no second session from a double click
    setBusy(true);
    setError(null);
    setNote(null);
    counters.current.clear();
    queues.current.clear();
    seqs.current.clear();
    finals.current.clear();
    let sid: string | null = null;
    const opened: MediaStream[] = []; // microphones opened by this attempt (closed if it fails)
    try {
      const res = await api.post<AudioSession>(`/meetings/${meetingId}/audio-sessions`, {
        sources: picked.map((p) => ({ id: p.id, kind: p.kind, label: p.label.trim() || p.id, single_speaker: p.singleSpeaker })),
        translate,
        language_detection: langMode,
        languages: langs,
        mode: !streamingWanted ? "chunked" : latency === "interpret" ? "interpret" : "streaming",
        noise_suppression: noise,
        caption_latency: latency === "interpret" ? "balanced" : latency,
        stt_provider: soniox ? "soniox" : "openai",
        consent_confirmed: consent,
      });
      sid = res.session.id;
      const sessionId = sid;
      const mode = res.session.capture_config?.mode;
      const streaming = mode === "streaming" || mode === "interpret";
      if (streamingWanted && !streaming) setNote(t.audio.streamingUnavailable);
      const t0 = performance.now();
      for (const p of picked) {
        if (unmounted.current) throw new Error("UNMOUNTED");
        let raw = p.stream;
        if (!raw) {
          raw = await openMicrophone(p.deviceId!, noise !== "off");
          opened.push(raw);
        }
        const cleaned = await denoise(raw, noise, p.kind === "microphone" ? "microphone" : "other");
        cleaners.current.set(p.id, cleaned);
        const stream = cleaned.stream;
        queues.current.set(p.id, []);
        seqs.current.set(p.id, 0);
        counters.current.set(p.id, { level: 0, queued: 0, sent: 0, errors: 0, echoes: 0, lastError: null });
        // In streaming mode the local segmenter only drives the level meter.
        const cap = new SourceCapture(stream, (u) => {
          // Streaming: the local sentence detector only tells OpenAI where an utterance ends.
          if (streaming) return realtime.current.get(p.id)?.commit();
          queues.current.get(p.id)?.push(u);
          void pump(sessionId, p.id);
        });
        captures.current.set(p.id, cap); // registered first so a failure below still releases it
        await cap.start(t0);
        if (streaming) await startStreaming(sessionId, p, stream, cap, t0, res.session.capture_config?.stt_provider ?? "openai");
      }
      if (unmounted.current) throw new Error("UNMOUNTED");
      setSessionId(sid);
      setSpeakers(res.speakers);
      onChanged();
    } catch (err) {
      realtime.current.forEach((r) => void r.stop());
      realtime.current.clear();
      captures.current.forEach((c) => void c.stop());
      captures.current.clear();
      cleaners.current.forEach((d) => void d.close());
      cleaners.current.clear();
      opened.forEach((s) => s.getTracks().forEach((tr) => tr.stop()));
      // The server session was created before the devices failed: end it, or the next
      // attempt would be refused ("a live session is already running").
      if (sid) await api.post(`/audio-sessions/${sid}/stop`).catch(() => undefined);
      if (unmounted.current) return;
      // Shared screen/tab audio was released by the cleanup above: it must be picked again.
      setPicked((prev) => prev.filter((p) => !p.stream || p.stream.getAudioTracks().some((tr) => tr.readyState === "live")));
      setError(mediaError(err));
      onChanged();
    } finally {
      if (!unmounted.current) setBusy(false);
    }
  }

  async function stop() {
    if (!sessionId) return;
    setBusy(true);
    const sid = sessionId;
    try {
      // Soniox sends its last tokens after the end of audio: wait for them (bounded).
      await Promise.all([...realtime.current.values()].map((r) => r.stop()));
      realtime.current.clear();
      voices.current.forEach((el) => {
        el.pause();
        el.srcObject = null;
      });
      voices.current.clear();
      await Promise.race([Promise.all([...finals.current.values()]), sleep(15000)]);
      finals.current.clear();
      setInterim({});
      picked.forEach((p) => onInterim?.(p.id, p.label, ""));
      await Promise.all([...captures.current.values()].map((c) => c.stop()));
      captures.current.clear();
      await Promise.all([...cleaners.current.values()].map((d) => d.close()));
      cleaners.current.clear();
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

            <section>
              <h3 className="mb-1 font-medium">{t.audio.languages}</h3>
              {streamingWanted && latency === "interpret" && !soniox ? (
                <p className="text-xs text-muted" data-testid="audio-languages-auto">{t.audio.languageDetect.interpret}</p>
              ) : (
                <>
                  <div className="mb-2 flex flex-wrap gap-2" role="radiogroup" aria-label={t.audio.languages} data-testid="language-detection">
                    {(["auto", "listed"] as const).map((m) => (
                      <button
                        key={m}
                        type="button"
                        role="radio"
                        aria-checked={langMode === m}
                        onClick={() => setLangMode(m)}
                        className={
                          "rounded-full border-2 border-ink px-3 py-1 text-xs font-bold transition-colors " +
                          (langMode === m ? "bg-brand-500 text-white" : "bg-white text-ink hover:bg-brand-50")
                        }
                      >
                        {t.audio.languageDetect[m]}
                      </button>
                    ))}
                  </div>
                  {langMode === "listed" && (
                    <div className="flex flex-wrap gap-4" data-testid="audio-languages">
                      {ALL_LANGS.map((l) => (
                        <Checkbox
                          key={l}
                          label={t.languages[l]}
                          checked={langs.includes(l)}
                          disabled={langs.length === 1 && langs.includes(l)}
                          onChange={(e) => setLangs(e.target.checked ? ALL_LANGS.filter((x) => x === l || langs.includes(x)) : langs.filter((x) => x !== l))}
                        />
                      ))}
                    </div>
                  )}
                  <p className="mt-1 text-xs text-muted">{langMode === "auto" ? t.audio.languageDetect.autoHint : t.audio.languagesHint}</p>
                </>
              )}
            </section>

            <section>
              <h3 className="mb-1 font-medium">{t.audio.noise.title}</h3>
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={t.audio.noise.title} data-testid="noise-level">
                {(["off", "standard", "strong"] as NoiseLevel[]).map((lv) => (
                  <button
                    key={lv}
                    type="button"
                    role="radio"
                    aria-checked={noise === lv}
                    onClick={() => setNoise(lv)}
                    className={
                      "rounded-full border-2 border-ink px-3 py-1 text-xs font-bold transition-colors " +
                      (noise === lv ? "bg-brand-500 text-white" : "bg-white text-ink hover:bg-brand-50")
                    }
                  >
                    {t.audio.noise[lv]}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-xs text-muted">{t.audio.noise.hint[noise]}</p>
            </section>

            <div className="flex flex-col items-start gap-2">
              <Checkbox label={t.audio.streaming} checked={streamingWanted} onChange={(e) => setStreamingWanted(e.target.checked)} data-testid="audio-streaming" />
              <p className="-mt-1 ml-6 text-xs text-muted">{streamingWanted ? t.audio.streamingHint : t.audio.chunkedHint}</p>
              {streamingWanted && (
                <div className="ml-6 flex flex-wrap items-center gap-2" role="radiogroup" aria-label={t.audio.provider.title} data-testid="stt-provider">
                  <span className="text-xs font-bold">{t.audio.provider.title}:</span>
                  {(["openai", "soniox"] as const).map((pv) => (
                    <button
                      key={pv}
                      type="button"
                      role="radio"
                      aria-checked={sttProvider === pv}
                      disabled={pv === "soniox" && !sonioxReady}
                      onClick={() => {
                        setSttProvider(pv);
                        if (pv === "soniox" && latency !== "interpret") setLatency("balanced");
                      }}
                      className={
                        "rounded-full border-2 border-ink px-3 py-1 text-xs font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-50 " +
                        (sttProvider === pv ? "bg-brand-500 text-white" : "bg-white text-ink hover:bg-brand-50")
                      }
                    >
                      {t.audio.provider[pv]}
                    </button>
                  ))}
                  <span className="w-full text-xs text-muted">{sonioxReady ? t.audio.provider.hint[sttProvider] : t.audio.provider.needKey}</span>
                </div>
              )}
              {streamingWanted && (
                <div className="ml-6 flex flex-wrap items-center gap-2" role="radiogroup" aria-label={t.audio.latency.title} data-testid="caption-latency">
                  <span className="text-xs font-bold">{t.audio.latency.title}:</span>
                  {(soniox ? (["interpret", "balanced"] as const) : (["interpret", "fast", "balanced", "accurate"] as const)).map((lv) => (
                    <button
                      key={lv}
                      type="button"
                      role="radio"
                      aria-checked={latency === lv}
                      onClick={() => setLatency(lv)}
                      className={
                        "rounded-full border-2 border-ink px-3 py-1 text-xs font-bold transition-colors " +
                        (latency === lv ? "bg-brand-500 text-white" : "bg-white text-ink hover:bg-brand-50")
                      }
                    >
                      {soniox && lv === "balanced" ? t.audio.latency.sonioxCaptions : t.audio.latency[lv]}
                    </button>
                  ))}
                  <span className="w-full text-xs text-muted">
                    {soniox ? (latency === "interpret" ? t.audio.latency.hint.sonioxInterpret : t.audio.latency.hint.sonioxCaptions) : t.audio.latency.hint[latency]}
                  </span>
                  {latency === "interpret" && !soniox && (
                    <Checkbox label={t.audio.playVoice} checked={playVoice} onChange={(e) => setPlayVoice(e.target.checked)} data-testid="play-voice" />
                  )}
                </div>
              )}
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
                      {s?.echoes ? ` · ${t.audio.echoes}: ${s.echoes}` : ""}
                    </span>
                    {noise !== "off" && (
                      <Badge tone={gates[p.id] ? "success" : "neutral"} title={t.audio.noise.title}>
                        {gates[p.id] ? t.audio.noise.passing : t.audio.noise.blocking}
                      </Badge>
                    )}
                    {conn[p.id] && <Badge tone={conn[p.id] === "connected" ? "success" : conn[p.id] === "failed" ? "danger" : "warning"}>{t.audio.conn[conn[p.id]]}</Badge>}
                    {s?.lastError && <span className="text-xs text-red-700">{s.lastError}</span>}
                  </li>
                );
              })}
            </ul>
            {!onInterim && Object.values(interim).some((x) => x.text || x.translation) && (
              <div className="rounded-md border border-sky-200 bg-sky-50 p-3" data-testid="interim-captions" aria-live="polite">
                <p className="mb-1 text-xs font-medium text-sky-900">{t.audio.speakingNow}</p>
                {picked
                  .filter((p) => interim[p.id]?.text || interim[p.id]?.translation)
                  .map((p) => (
                    <p key={p.id} className="text-base text-ink">
                      <span className="mr-2 text-xs font-medium text-muted">{p.label}:</span>
                      {interim[p.id].translation || interim[p.id].text}
                      <span className="ml-0.5 animate-pulse">▍</span>
                    </p>
                  ))}
              </div>
            )}
            {Object.values(stats).some((x) => x.echoes > 0) && <Alert tone="info">{t.audio.echoTipLive}</Alert>}
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
