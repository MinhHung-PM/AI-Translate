"use client";

import type { SourceCapture } from "./capture";
import type { RealtimeHandlers } from "./realtime-events";
import type { CaptionState, RealtimeToken } from "./realtime";
import { SonioxEventProcessor } from "./soniox-events";

const RATE = 16000;
const SEND_EVERY_MS = 100;
const MAX_BUFFER_SAMPLES = RATE * 8; // audio kept while (re)connecting

/**
 * Streams one source to Soniox over its real-time WebSocket using a temporary,
 * single-use key from our server. The first message is the session config built by
 * the server (+ the temporary key as ``api_key``); then 16 kHz mono PCM16 audio taken
 * from the same capture pipeline as the other modes. Audio goes directly from the
 * browser to Soniox; the user's Soniox key never leaves the server.
 */
export class SonioxCaptionSource {
  private ws: WebSocket | null = null;
  private chunks: Float32Array[] = [];
  private buffered = 0;
  private sendTimer: ReturnType<typeof setInterval> | null = null;
  private idleTimer: ReturnType<typeof setInterval> | null = null;
  private processor: SonioxEventProcessor | null = null;
  private stopped = false;
  private attempts = 0;
  private finished: (() => void) | null = null;
  model = "";
  onRemoteAudio: ((stream: MediaStream) => void) | null = null;
  readonly interpreted: boolean;

  constructor(
    private readonly capture: SourceCapture,
    private readonly getToken: () => Promise<RealtimeToken>,
    private readonly handlers: RealtimeHandlers,
    private readonly clock: () => number,
    private readonly onState: (s: CaptionState, reconnects: number) => void,
    translating: boolean,
  ) {
    this.interpreted = translating;
    capture.onSamples = (s) => this.buffer(s);
  }

  private buffer(samples: Float32Array): void {
    if (this.stopped || !samples.length) return;
    this.chunks.push(samples);
    this.buffered += samples.length;
    while (this.buffered > MAX_BUFFER_SAMPLES && this.chunks.length > 1) this.buffered -= this.chunks.shift()!.length;
  }

  async start(): Promise<void> {
    if (this.stopped) return;
    this.onState(this.attempts ? "reconnecting" : "connecting", this.attempts);
    const token = await this.getToken();
    // Stop may be clicked while connecting: never open a socket behind it.
    if (this.stopped) return;
    if (token.kind !== "soniox" || !token.session_config) throw new Error("Not a Soniox session");
    this.model = token.model;
    if (!this.processor) {
      this.processor = new SonioxEventProcessor(this.handlers, !!token.session_config.translation);
      this.processor.now = this.clock;
    }
    const ws = new WebSocket(token.calls_url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => {
        ws.send(JSON.stringify({ ...token.session_config, api_key: token.client_secret }));
        // Soniox timestamps count from the first audio byte of this connection.
        this.processor!.baseMs = this.clock() - (this.buffered / RATE) * 1000;
        this.attempts = 0;
        this.onState("connected", 0);
        resolve();
      };
      ws.onerror = () => reject(new Error("Could not connect to Soniox"));
    });
    if (this.stopped && !this.finished) {
      this.ws = null;
      ws.close();
      return;
    }
    ws.onmessage = (e: MessageEvent<string>) => {
      if (typeof e.data !== "string") return;
      this.processor?.handle(e.data);
      if (this.finished && /"finished"\s*:\s*true/.test(e.data)) this.finished();
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (this.finished) return this.finished();
      if (!this.stopped) void this.reconnect();
    };
    if (!this.sendTimer) this.sendTimer = setInterval(() => this.flushAudio(), SEND_EVERY_MS);
    // Safety net: close a sentence whose endpoint/translation never arrived.
    if (!this.idleTimer) this.idleTimer = setInterval(() => this.processor?.flushIdle(4000), 250);
  }

  private flushAudio(): void {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN || !this.buffered) return;
    const pcm = new Int16Array(this.buffered);
    let i = 0;
    for (const c of this.chunks) {
      for (let k = 0; k < c.length; k++) {
        const v = Math.max(-1, Math.min(1, c[k]));
        pcm[i++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      }
    }
    this.chunks = [];
    this.buffered = 0;
    ws.send(pcm.buffer);
  }

  /** Soniox detects utterance ends itself (endpoint detection); nothing to do. */
  commit(): void {}

  private async reconnect(): Promise<void> {
    if (this.stopped) return;
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

  /** Sends the remaining audio, asks Soniox to finish and waits (bounded) for the last tokens. */
  async stop(): Promise<void> {
    if (this.stopped) return;
    this.stopped = true;
    this.capture.onSamples = null;
    this.flushAudio();
    const ws = this.ws;
    if (ws && ws.readyState === WebSocket.OPEN) {
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, 4000);
        this.finished = () => {
          clearTimeout(timer);
          resolve();
        };
        ws.send(""); // end of audio: Soniox finalizes and replies {finished: true}
      });
    }
    if (this.sendTimer) clearInterval(this.sendTimer);
    if (this.idleTimer) clearInterval(this.idleTimer);
    this.sendTimer = this.idleTimer = null;
    this.processor?.flushIdle(0);
    this.ws = null;
    ws?.close();
    this.onState("closed", this.attempts);
  }
}
