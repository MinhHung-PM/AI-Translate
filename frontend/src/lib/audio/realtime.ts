"use client";

import { RealtimeEventProcessor, type RealtimeHandlers } from "./realtime-events";

export interface RealtimeToken {
  client_secret: string;
  expires_at: number;
  model: string;
  calls_url: string;
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
  private stopped = false;
  private attempts = 0;
  readonly processor: RealtimeEventProcessor;
  model = "";

  constructor(
    private readonly stream: MediaStream,
    private readonly getToken: () => Promise<RealtimeToken>,
    handlers: RealtimeHandlers,
    private readonly clock: () => number,
    private readonly onState: (s: CaptionState, reconnects: number) => void,
  ) {
    this.processor = new RealtimeEventProcessor(handlers);
    this.processor.now = clock;
  }

  async start(): Promise<void> {
    this.onState(this.attempts ? "reconnecting" : "connecting", this.attempts);
    const token = await this.getToken();
    this.model = token.model;
    const pc = new RTCPeerConnection();
    this.pc = pc;
    for (const track of this.stream.getAudioTracks()) pc.addTrack(track, this.stream);
    const dc = pc.createDataChannel("oai-events");
    dc.onmessage = (e: MessageEvent<string>) => this.processor.handle(e.data);
    dc.onopen = () => {
      this.processor.baseMs = this.clock();
      this.attempts = 0;
      this.onState("connected", 0);
    };
    pc.onconnectionstatechange = () => {
      if (this.stopped || this.pc !== pc) return;
      if (pc.connectionState === "failed" || pc.connectionState === "disconnected") void this.reconnect();
    };
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const res = await fetch(token.calls_url, {
      method: "POST",
      body: offer.sdp,
      headers: { Authorization: `Bearer ${token.client_secret}`, "Content-Type": "application/sdp" },
    });
    if (!res.ok) throw new Error(`OpenAI Realtime rejected the connection (${res.status})`);
    await pc.setRemoteDescription({ type: "answer", sdp: await res.text() });
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
    try {
      await this.start();
    } catch {
      void this.reconnect();
    }
  }

  stop(): void {
    this.stopped = true;
    this.pc?.close();
    this.pc = null;
    this.onState("closed", this.attempts);
  }
}
