"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { Alert, Badge, Button, Checkbox, Chip, Fred, FredSays, cn } from "@/components/ui";
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
import { useSession } from "@/lib/session";
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
  onRunningChange,
  captions,
  toolbar,
  lineCount,
}: {
  meetingId: string;
  session: LiveSession | null;
  defaultLanguages: Language[];
  onChanged: () => void;
  /** Words being spoken, reported to the parent's caption feed. */
  onInterim?: (sourceId: string, label: string, text: string, translation?: string) => void;
  /** Capture started / stopped in this browser (the page switches to its focus layout). */
  onRunningChange?: (running: boolean) => void;
  /** While capturing: the caption feed (fills the screen) and its display controls (status bar). */
  captions?: ReactNode;
  toolbar?: ReactNode;
  lineCount?: number;
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
  const { session: me } = useSession();
  // Soniox is usable with the user's own key, or the server's key on a shared team site.
  const sonioxReady = !!me?.features.server_soniox || !!providerConfigs.data?.some((c) => c.provider === "soniox" && c.has_usable_key);
  const soniox = streamingWanted && sttProvider === "soniox";
  const voices = useRef(new Map<string, HTMLAudioElement>());
  const [gates, setGates] = useState<Record<string, boolean>>({});
  const [conn, setConn] = useState<Record<string, CaptionState>>({});
  const [advanced, setAdvanced] = useState(false);
  const [startedAt, setStartedAt] = useState(0);
  const [now, setNow] = useState(0);

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

  useEffect(() => {
    onRunningChange?.(running);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  // Recording clock in the status bar.
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
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
      setStartedAt(Date.now());
      setNow(Date.now());
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
  const elapsedSec = running && startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : 0;
  const clock = `${String(Math.floor(elapsedSec / 60)).padStart(2, "0")}:${String(elapsedSec % 60).padStart(2, "0")}`;
  const interpret = streamingWanted && latency === "interpret";
  const advSummary = [
    streamingWanted ? t.audio.provider[sttProvider].split(" ")[0] : t.audio.chunkedShort,
    streamingWanted ? (soniox && latency === "balanced" ? t.audio.latency.sonioxCaptions : t.audio.latency[latency]).replace(/\s*\(.*\)$/, "") : null,
    interpret && !soniox ? t.audio.languageDetect.autoShort : langMode === "auto" ? t.audio.languageDetect.autoShort : langs.join("/"),
    `${t.audio.noise.short} ${t.audio.noise.levelShort[noise]}`,
  ]
    .filter(Boolean)
    .join(" · ");

  const alerts = (
    <>
      {error && <Alert tone="danger" fred="sad">{error}</Alert>}
      {note && <Alert tone="warning">{note}</Alert>}
      {orphan && (
        <Alert tone="warning">
          {t.audio.orphan}{" "}
          <Button size="sm" className="mt-1" onClick={() => void endOrphan()}>
            {t.audio.endOrphan}
          </Button>
        </Alert>
      )}
    </>
  );

  if (running) {
    const failing = picked.filter((p) => stats[p.id]?.lastError || conn[p.id] === "failed" || conn[p.id] === "reconnecting");
    return (
      <div className="flex min-h-0 flex-1 flex-col" data-testid="audio-capture">
        {/* Thin status bar: recording clock, one pill per source, caption controls, stop. */}
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-[clamp(14px,2.4vw,28px)] py-2 text-xs">
          <span className="flex items-center gap-1.5 font-mono text-xs font-medium text-danger">
            <span className="size-2 animate-rec rounded-full bg-danger" aria-hidden />
            <span aria-label={t.audio.elapsed}>{clock}</span>
          </span>
          <span className="flex flex-wrap items-center gap-2" data-testid="audio-sources-live">
            {picked.map((p) => {
              const s = stats[p.id];
              const level = Math.min(100, Math.round((s?.level ?? 0) * 400));
              const state = conn[p.id];
              const bad = state === "failed" || state === "reconnecting" || !!s?.lastError;
              const passing = noise === "off" || gates[p.id];
              return (
                <span
                  key={p.id}
                  title={`${t.audio.sent}: ${s?.sent ?? 0} · ${t.audio.queued}: ${s?.queued ?? 0}${s?.errors ? ` · ${t.audio.errors}: ${s.errors}` : ""}${s?.echoes ? ` · ${t.audio.echoes}: ${s.echoes}` : ""}`}
                  className={cn("flex items-center gap-1.5 rounded-full border px-2.5 py-1 whitespace-nowrap", bad ? "border-danger-line bg-danger-soft" : "border-line")}
                >
                  <span className="flex h-3 items-end gap-0.5" role="meter" aria-label={`${t.audio.level} ${p.label}`} aria-valuenow={level} aria-valuemin={0} aria-valuemax={100}>
                    {[4, level > 30 ? 8 : 4, level > 65 ? 12 : 4].map((h, i) => (
                      <span key={i} className={cn("w-[3px] rounded-[1px] transition-[height]", bad ? "bg-danger" : "bg-info")} style={{ height: h }} />
                    ))}
                  </span>
                  <span className="max-w-36 truncate">{p.label}</span>
                  {state && state !== "connected" ? (
                    <span className={state === "failed" ? "text-danger" : "text-warning"}>{t.audio.conn[state]}</span>
                  ) : (
                    <>
                      {/* Streaming: a green dot says the connection is up; the words say whether voice gets through. */}
                      {state === "connected" && (
                        <span className="size-1.5 rounded-full bg-success" title={t.audio.conn.connected}>
                          <span className="sr-only">{t.audio.conn.connected}</span>
                        </span>
                      )}
                      {noise !== "off" ? (
                        <span className={passing ? "text-success" : "text-muted"}>{passing ? t.audio.noise.passing : t.audio.noise.blocking}</span>
                      ) : (
                        !state && <span className="text-success">{t.audio.listening}</span>
                      )}
                    </>
                  )}
                  <span className="sr-only" data-testid={`sent-${p.id}`}>
                    {s?.sent ?? 0}
                  </span>
                </span>
              );
            })}
          </span>
          {lineCount !== undefined && (
            <span className="text-muted">
              {lineCount} {t.audio.lines}
            </span>
          )}
          <span className="flex-1" />
          <div className="flex flex-wrap items-center gap-1">
            {toolbar}
            <button
              type="button"
              onClick={() => void stop()}
              disabled={busy}
              className="ml-1 inline-flex items-center gap-1.5 rounded-lg bg-ink px-3 py-1 font-semibold text-bg disabled:opacity-60"
              data-testid="stop-audio"
            >
              {busy && <span className="size-3 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />}
              {t.audio.stop}
            </button>
          </div>
        </div>

        {/* Problems sit under the bar so they never cover the captions. */}
        {(error || note || lagging || failing.length > 0 || Object.values(stats).some((x) => x.echoes > 0)) && (
          <div className="flex flex-col gap-2 px-[clamp(14px,2.4vw,28px)] pt-2.5">
            {error && <Alert tone="danger" fred="sad">{error}</Alert>}
            {failing.map((p) => (
              <Alert key={p.id} tone="danger" fred="sad">
                <b>{p.label}</b> · {conn[p.id] ? t.audio.conn[conn[p.id]] : t.audio.sttError}
                {stats[p.id]?.lastError && ` — ${stats[p.id].lastError}`}
              </Alert>
            ))}
            {note && <Alert tone="warning">{note}</Alert>}
            {lagging && <Alert tone="warning">{t.audio.lag}</Alert>}
            {Object.values(stats).some((x) => x.echoes > 0) && <Alert tone="info">{t.audio.echoTipLive}</Alert>}
          </div>
        )}

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">{captions}</div>
          <aside className="hidden w-[230px] shrink-0 flex-col gap-2.5 border-l border-line bg-surface p-4 @min-[1000px]:flex" data-testid="audio-speakers">
            <span className="eyebrow text-muted">{t.audio.speakersHint}</span>
            {speakers.length === 0 ? (
              <p className="text-xs leading-normal text-muted">{t.audio.noSpeakers}</p>
            ) : (
              speakers.map((s, i) => (
                <div key={s.speaker_key} className="flex items-center gap-2">
                  <span className={cn("size-2.5 shrink-0 rounded-full", ["bg-spk1", "bg-spk2", "bg-spk3", "bg-info"][i % 4])} aria-hidden />
                  <input
                    aria-label={`${t.audio.rename} ${s.speaker_key}`}
                    value={names[s.speaker_key] ?? s.display_name}
                    maxLength={200}
                    onChange={(e) => setNames({ ...names, [s.speaker_key]: e.target.value })}
                    onBlur={() => names[s.speaker_key] && names[s.speaker_key] !== s.display_name && void rename(s.speaker_key)}
                    onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
                    className="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-sm outline-none hover:border-line focus:border-info focus:bg-bg"
                  />
                  <span className="font-mono text-[11px] text-subtle">{s.segments}</span>
                </div>
              ))
            )}
            <p className="text-[11px] leading-normal text-subtle">{t.audio.unattributed}</p>
            <div className="mt-auto flex flex-col items-center gap-2">
              <Fred pose="headphones" alt={t.fred.listeningAlt} className="w-full animate-floaty" />
              <FredSays className="bg-transparent p-0 text-center text-xs font-normal text-muted">{t.fred.listening}</FredSays>
            </div>
          </aside>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto grid w-full max-w-[1100px] items-start gap-7 p-[clamp(16px,3vw,36px)] @min-[1100px]:grid-cols-[minmax(0,1fr)_340px]" data-testid="audio-capture">
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <span className="eyebrow text-[11px] tracking-[.08em] text-accent-text">{t.audio.setupEyebrow}</span>
          <h2 className="font-display text-[clamp(22px,2.6vw,30px)] leading-[1.15] font-semibold">{t.audio.setupTitle}</h2>
          <p className="text-sm text-muted">{t.audio.intro}</p>
        </div>
        {alerts}

        {!orphan && (
          <>
            <div className="flex flex-col gap-2.5">
              {picked.length > 0 && (
                <ul className="flex flex-col gap-2.5" data-testid="picked-sources">
                  {picked.map((p) => (
                    <li key={p.id} className="flex flex-col gap-2.5 rounded-[14px] border border-line bg-surface p-3.5">
                      <div className="flex flex-wrap items-center gap-2.5">
                        <Badge>{p.kind === "microphone" ? t.audio.kindMic : t.audio.kindMeeting}</Badge>
                        <span className="min-w-28 flex-1 truncate text-[13px] text-muted">{p.kind === "microphone" ? (mics?.find((m) => m.deviceId === p.deviceId)?.label ?? t.audio.microphones) : t.audio.sharedTab}</span>
                        <button type="button" onClick={() => remove(p.id)} className="text-[13px] text-muted hover:text-danger">
                          {t.audio.remove}
                        </button>
                      </div>
                      <label className="flex flex-col gap-1">
                        <span className="text-xs text-muted">{t.audio.labelFor}</span>
                        <input
                          value={p.label}
                          maxLength={80}
                          onChange={(e) => update(p.id, { label: e.target.value })}
                          className="rounded-[10px] border border-line-strong bg-bg px-3 py-2 text-sm outline-none focus:border-info"
                        />
                      </label>
                      <Checkbox label={t.audio.singleSpeaker} checked={p.singleSpeaker} onChange={(e) => update(p.id, { singleSpeaker: e.target.checked })} className="text-[13px] text-muted" />
                      {p.kind === "system" && (
                        <div className="flex items-start gap-2.5 rounded-[10px] bg-info-soft px-3 py-2.5 text-[13px] leading-normal">
                          <span className="font-bold text-info" aria-hidden>
                            i
                          </span>
                          <span>{t.audio.systemHelp}</span>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}

              {mics && (
                <div className="rounded-[14px] border border-line bg-surface p-3.5">
                  <p className="mb-2 text-xs text-muted">{t.audio.microphones}</p>
                  {mics.length === 0 ? (
                    <p className="text-[13px] text-muted">{t.audio.noMics}</p>
                  ) : (
                    <ul className="flex flex-col gap-1.5" data-testid="mic-list">
                      {mics.map((d) => (
                        <li key={d.deviceId}>
                          <Checkbox label={d.label || d.deviceId} checked={picked.some((p) => p.deviceId === d.deviceId)} onChange={(e) => toggleMic(d, e.target.checked)} />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                {mics === null && (
                  <button type="button" onClick={() => void loadMics()} className="rounded-[10px] border border-dashed border-line-strong px-3.5 py-2 text-[13px] hover:bg-surface-2" data-testid="unlock-mics">
                    + {t.audio.addMic}
                  </button>
                )}
                <button type="button" onClick={() => void addSystem()} className="rounded-[10px] border border-dashed border-line-strong px-3.5 py-2 text-[13px] hover:bg-surface-2" data-testid="add-system-audio">
                  + {t.audio.addSystem}
                </button>
              </div>
              {picked.length === 0 && <p className="text-[13px] text-muted">{t.audio.systemHelp}</p>}
              <p className="text-xs text-subtle">{t.audio.echoTip}</p>
            </div>

            <div className="overflow-hidden rounded-[14px] border border-line">
              <button
                type="button"
                onClick={() => setAdvanced(!advanced)}
                aria-expanded={advanced}
                className="flex w-full items-center gap-2.5 bg-surface px-4 py-3 text-left"
                data-testid="advanced-toggle"
              >
                <span className="flex-1 text-sm font-semibold">{t.audio.advanced}</span>
                <span className="hidden truncate text-xs text-muted sm:block">{advSummary}</span>
                <span className="text-muted" aria-hidden>
                  {advanced ? "▴" : "▾"}
                </span>
              </button>
              {advanced && (
                <div className="flex flex-col gap-4 border-t border-line bg-surface px-4 pt-2 pb-4">
                  <OptionGroup label={t.audio.provider.title} hint={streamingWanted ? (sonioxReady ? t.audio.provider.hint[sttProvider] : t.audio.provider.needKey) : undefined}>
                    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t.audio.provider.title} data-testid="stt-provider">
                      {(["openai", "soniox"] as const).map((pv) => (
                        <Chip
                          key={pv}
                          role="radio"
                          on={sttProvider === pv}
                          disabled={!streamingWanted || (pv === "soniox" && !sonioxReady)}
                          onClick={() => {
                            setSttProvider(pv);
                            if (pv === "soniox" && latency !== "interpret") setLatency("balanced");
                          }}
                        >
                          {t.audio.provider[pv]}
                        </Chip>
                      ))}
                    </div>
                  </OptionGroup>

                  <OptionGroup
                    label={t.audio.latency.title}
                    hint={streamingWanted ? (soniox ? (latency === "interpret" ? t.audio.latency.hint.sonioxInterpret : t.audio.latency.hint.sonioxCaptions) : t.audio.latency.hint[latency]) : t.audio.chunkedHint}
                  >
                    {streamingWanted && (
                      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t.audio.latency.title} data-testid="caption-latency">
                        {(soniox ? (["interpret", "balanced"] as const) : (["interpret", "fast", "balanced", "accurate"] as const)).map((lv) => (
                          <Chip key={lv} role="radio" on={latency === lv} onClick={() => setLatency(lv)}>
                            {soniox && lv === "balanced" ? t.audio.latency.sonioxCaptions : t.audio.latency[lv]}
                          </Chip>
                        ))}
                      </div>
                    )}
                    <Checkbox label={t.audio.streaming} checked={streamingWanted} onChange={(e) => setStreamingWanted(e.target.checked)} data-testid="audio-streaming" className="text-[13px]" />
                  </OptionGroup>

                  <OptionGroup
                    label={t.audio.languages}
                    hint={interpret && !soniox ? undefined : langMode === "auto" ? t.audio.languageDetect.autoHint : t.audio.languagesHint}
                  >
                    {interpret && !soniox ? (
                      <p className="text-[13px] text-muted" data-testid="audio-languages-auto">
                        {t.audio.languageDetect.interpret}
                      </p>
                    ) : (
                      <>
                        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t.audio.languages} data-testid="language-detection">
                          {(["auto", "listed"] as const).map((m) => (
                            <Chip key={m} role="radio" on={langMode === m} onClick={() => setLangMode(m)}>
                              {t.audio.languageDetect[m]}
                            </Chip>
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
                      </>
                    )}
                  </OptionGroup>

                  <OptionGroup label={t.audio.noise.title} hint={t.audio.noise.hint[noise]}>
                    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t.audio.noise.title} data-testid="noise-level">
                      {(["off", "standard", "strong"] as NoiseLevel[]).map((lv) => (
                        <Chip key={lv} role="radio" on={noise === lv} onClick={() => setNoise(lv)}>
                          {t.audio.noise[lv]}
                        </Chip>
                      ))}
                    </div>
                  </OptionGroup>

                  <div className="flex flex-col gap-2 pt-1">
                    <Checkbox label={t.audio.translate} checked={translate} onChange={(e) => setTranslate(e.target.checked)} />
                    {interpret && !soniox && <Checkbox label={t.audio.playVoice} checked={playVoice} onChange={(e) => setPlayVoice(e.target.checked)} data-testid="play-voice" />}
                  </div>
                </div>
              )}
            </div>

            <label className={cn("flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 text-sm leading-normal", consent ? "border-line bg-surface" : "border-accent bg-accent-soft")}>
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 size-[18px] shrink-0 accent-accent" data-testid="audio-consent" />
              <span>
                {t.audio.consent} <span className="text-danger">*</span>
              </span>
            </label>

            <div className="flex flex-wrap items-center gap-3.5">
              <Button variant="primary" size="lg" onClick={() => void start()} loading={busy} disabled={!consent || picked.length === 0} data-testid="start-audio">
                <span className="size-[9px] rounded-full bg-[#d93a2b]" aria-hidden />
                {t.audio.start}
              </Button>
              <span className="text-[13px] text-muted">{!consent ? t.audio.needConsent : picked.length === 0 ? t.audio.needSource : t.audio.ready.replace("{n}", String(picked.length))}</span>
            </div>
          </>
        )}

        {speakers.length > 0 && (
          <section className="flex flex-col gap-2 rounded-[14px] border border-line bg-surface p-3.5" data-testid="audio-speakers">
            <h3 className="eyebrow text-muted">{t.audio.speakers}</h3>
            {speakers.map((s) => (
              <div key={s.speaker_key} className="flex flex-wrap items-center gap-2">
                <Badge>{s.speaker_key}</Badge>
                <input
                  aria-label={`${t.audio.rename} ${s.speaker_key}`}
                  value={names[s.speaker_key] ?? s.display_name}
                  maxLength={200}
                  onChange={(e) => setNames({ ...names, [s.speaker_key]: e.target.value })}
                  className="w-48 rounded-lg border border-line-strong bg-bg px-2.5 py-1.5 text-sm outline-none focus:border-info"
                />
                <Button size="sm" onClick={() => void rename(s.speaker_key)} disabled={!names[s.speaker_key] || names[s.speaker_key] === s.display_name}>
                  {t.audio.save}
                </Button>
                <span className="text-xs text-muted">{s.segments}</span>
              </div>
            ))}
          </section>
        )}
      </div>

      <div className="sticky top-24 hidden flex-col items-center @min-[1100px]:flex">
        <FredSays className="max-w-[280px] self-start">{consent ? t.fred.setupReady : t.fred.setupDefaults}</FredSays>
        <Fred pose={consent ? "pointing" : "crossed"} alt={consent ? t.fred.pointingAlt : t.fred.crossedAlt} className="w-[min(100%,360px)] drop-shadow-[0_20px_36px_rgba(0,0,0,.35)]" />
      </div>
    </div>
  );
}

function OptionGroup({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 pt-2.5">
      <span className="text-xs text-muted">{label}</span>
      {children}
      {hint && <p className="text-xs leading-normal text-subtle">{hint}</p>}
    </div>
  );
}
