"use client";

import { RealtimeEventProcessor, type RealtimeHandlers } from "./realtime-events";
import { TranslationEventProcessor } from "./translation-events";

export interface RealtimeToken {
  client_secret: string;
  expires_at: number;
  model: string;
  calls_url: string;
  /** No server VAD: the browser commits each utterance (input_audio_buffer.commit). */
  client_commits?: boolean;
  /** "translation": live interpretation (gpt-realtime-translate) — translated words stream in. */
  kind?: "transcription" | "translation" | "soniox";
  target_language?: string | null;
  /** Soniox: config sent as the first WebSocket message (the browser adds the temporary key). */
  session_config?: Record<string, unknown> & { translation?: { target_language: string } };
}

export type CaptionState = "connecting" | "connected" | "reconnecting" | "failed" | "closed";

/**
 * Streams one MediaStream to OpenAI Realtime transcription over WebRTC using a
 * short-lived client secret from our server, and turns server events into
 * interim / final captions. Reconnects with a fresh token if the connection
 * drops (bounded). Audio goes directly from the browser to OpenAI.
 */
export class RealtimeCaptionSource {
  private pc: RTCPeerConnection | null = null;
  private dc: RTCDataChannel | null = null;
  private clientCommits = false;
  private staleTimer: ReturnType<typeof setInterval> | null = null;
  private stopped = false;
  private attempts = 0;
  private readonly captions: RealtimeEventProcessor;
  private readonly handlers: RealtimeHandlers;
  private readonly interpreter: TranslationEventProcessor;
  private interpreting = false;
  /** Interpret mode: a transcription session recording the original words (audit trail). */
  private companion: RealtimeCaptionSource | null = null;
  model = "";
  /** Live interpretation also returns translated speech; set to play it. */
  onRemoteAudio: ((stream: MediaStream) => void) | null = null;

  constructor(
    private readonly stream: MediaStream,
    private readonly getToken: () => Promise<RealtimeToken>,
    handlers: RealtimeHandlers,
    private readonly clock: () => number,
    private readonly onState: (s: CaptionState, reconnects: number) => void,
    /** Token for the companion transcription session (interpret mode). */
    private readonly getSourceToken: (() => Promise<RealtimeToken>) | null = null,
  ) {
    this.handlers = handlers;
    this.captions = new RealtimeEventProcessor(handlers);
    this.captions.now = clock;
    this.interpreter = new TranslationEventProcessor(handlers);
    this.interpreter.now = clock;
  }

  get interpreted(): boolean {
    return this.interpreting;
  }

  private lastMessageAt = 0;

  private handle(data: string): void {
    this.lastMessageAt = Date.now();
    if (this.interpreting) this.interpreter.handle(data);
    else this.captions.handle(data);
  }

  /** Save text that will get no further words (stale caption / speaker paused). */
  private flush(force: boolean): void {
    if (this.interpreting) this.interpreter.flushIdle(force ? 0 : 1300);
    else this.captions.flushStale(force ? 0 : 7000);
  }

  async start(): Promise<void> {
    if (this.stopped) return;
    this.onState(this.attempts ? "reconnecting" : "connecting", this.attempts);
    const token = await this.getToken();
    if (this.stopped) return;
    this.model = token.model;
    this.clientCommits = !!token.client_commits;
    this.interpreting = token.kind === "translation";
    if (this.interpreting) await this.startCompanion();
    if (this.stopped) return;
    const pc = new RTCPeerConnection();
    this.pc = pc;
    for (const track of this.stream.getAudioTracks()) pc.addTrack(track, this.stream);
    const dc = pc.createDataChannel("oai-events");
    this.dc = dc;
    dc.onmessage = (e: MessageEvent<string>) => this.handle(e.data);
    pc.ontrack = ({ streams }) => {
      if (streams[0]) this.onRemoteAudio?.(streams[0]);
    };
    dc.onopen = () => {
      this.captions.baseMs = this.interpreter.baseMs = this.clock();
      this.attempts = 0;
      this.onState("connected", 0);
      // Captions: safety net if a "completed" event never arrives. Interpretation has no
      // "completed" event at all: a sentence ends when the words stop.
      if (!this.staleTimer) this.staleTimer = setInterval(() => this.flush(false), 250);
    };
    pc.onconnectionstatechange = () => {
      if (this.stopped || this.pc !== pc) return;
      if (pc.connectionState === "failed" || pc.connectionState === "disconnected") void this.reconnect();
    };
    // Stop may be clicked while connecting: never leave a connection open behind it.
    const abandoned = () => {
      if (!this.stopped) return false;
      pc.close();
      if (this.pc === pc) this.pc = null;
      return true;
    };
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    if (abandoned()) return;
    const res = await fetch(token.calls_url, {
      method: "POST",
      body: offer.sdp,
      headers: { Authorization: `Bearer ${token.client_secret}`, "Content-Type": "application/sdp" },
    });
    if (!res.ok) {
      pc.close();
      throw new Error(`OpenAI Realtime rejected the connection (${res.status})`);
    }
    const answer = await res.text();
    if (abandoned()) return;
    await pc.setRemoteDescription({ type: "answer", sdp: answer });
  }

  /**
   * The interpreter's own source transcript is optional and did not arrive reliably, so the original
   * words come from a second, transcription-only session on the same audio, paired with the
   * translations by the interpreter's processor. If it cannot start, the interpreter's own source
   * transcript is used (when the server enables it).
   */
  private async startCompanion(): Promise<void> {
    if (this.companion || !this.getSourceToken) return;
    const companion = new RealtimeCaptionSource(
      this.stream,
      this.getSourceToken,
      {
        onInterim: (_id, text) => this.interpreter.setSourceInterim(text),
        onFinal: (u) => this.interpreter.addSource(u.text, u.startMs),
        onError: (m) => this.handlers.onError(m),
      },
      this.clock,
      () => undefined,
    );
    try {
      await companion.start();
      this.companion = companion;
      this.interpreter.externalSource = true;
    } catch (err) {
      void companion.stop();
      this.handlers.onError(`Original-words transcription unavailable: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  /** End of an utterance detected locally (pause or 12 s cap): ask OpenAI to finalize it. */
  commit(): void {
    this.companion?.commit();
    if (!this.clientCommits || this.dc?.readyState !== "open") return;
    this.dc.send(JSON.stringify({ type: "input_audio_buffer.commit" }));
  }

  private async reconnect(): Promise<void> {
    if (this.stopped) return;
    this.pc?.close();
    this.pc = null;
    this.attempts += 1;
    if (this.attempts > 5) {
      this.onState("failed", this.attempts);
      return;
    }
    await new Promise((r) => setTimeout(r, Math.min(8000, 1000 * 2 ** (this.attempts - 1))));
    if (this.stopped) return;
    try {
      await this.start();
    } catch {
      void this.reconnect();
    }
  }

  /**
   * Finishes the last sentence before closing: commits the pending audio and waits (bounded)
   * until OpenAI stops sending words — the interpreter runs a few seconds behind the speaker.
   */
  async stop(): Promise<void> {
    if (this.stopped) return;
    // The original words first: their last sentence must be there to pair with the last translation.
    await this.companion?.stop();
    this.commit();
    this.stopped = true;
    if (this.dc?.readyState === "open") {
      const quietMs = this.interpreting ? 2000 : 1200;
      const deadline = Date.now() + (this.interpreting ? 6000 : 4000);
      this.lastMessageAt = Math.max(this.lastMessageAt, Date.now());
      while (Date.now() < deadline && Date.now() - this.lastMessageAt < quietMs) {
        await new Promise((r) => setTimeout(r, 100));
      }
    }
    this.flush(true);
    if (this.staleTimer) clearInterval(this.staleTimer);
    this.staleTimer = null;
    this.pc?.close();
    this.pc = null;
    this.onState("closed", this.attempts);
  }
}
