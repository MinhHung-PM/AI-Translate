"use client";

import { Downsampler } from "./resample";
import { UtteranceSegmenter, type Utterance } from "./segmenter";

const TARGET_RATE = 16000;

// Static worklet module (public/audio-worklets/mono-tap.js), same origin → allowed by CSP 'self'.
const WORKLET_URL = "/audio-worklets/mono-tap.js";

export type SourceKind = "microphone" | "system" | "tab" | "device";

/**
 * Captures one MediaStream: mono → 16 kHz → voice activity segmentation.
 * Completed utterances are delivered to ``onUtterance`` with their offset
 * from ``t0`` (a shared clock, so sources can be ordered against each other).
 * Nothing is recorded or stored by this class.
 */
export class SourceCapture {
  private ctx: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private segmenter = new UtteranceSegmenter({ sampleRate: TARGET_RATE });
  private downsampler: Downsampler | null = null;
  private offsetBaseMs = 0;
  level = 0;
  /** Optional tap on the 16 kHz mono samples (e.g. streamed to Soniox). */
  onSamples: ((samples: Float32Array) => void) | null = null;

  constructor(
    readonly stream: MediaStream,
    private readonly onUtterance: (u: Utterance) => void,
  ) {}

  /** Offset (ms) of this capture's first sample from the shared clock ``t0``. */
  get startOffsetMs(): number {
    return this.offsetBaseMs;
  }

  async start(t0: number): Promise<void> {
    const ctx = new AudioContext();
    this.ctx = ctx;
    await ctx.audioWorklet.addModule(WORKLET_URL);
    this.downsampler = new Downsampler(ctx.sampleRate, TARGET_RATE);
    this.offsetBaseMs = Math.max(0, performance.now() - t0);
    this.source = ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(ctx, "mono-tap");
    this.node.port.onmessage = (ev: MessageEvent<Float32Array>) => this.handle(ev.data);
    this.source.connect(this.node);
    // Keep the graph pulling without playing anything back (avoids echo).
    const sink = ctx.createGain();
    sink.gain.value = 0;
    this.node.connect(sink).connect(ctx.destination);
    if (ctx.state === "suspended") await ctx.resume();
  }

  private handle(block: Float32Array): void {
    if (!this.downsampler) return;
    const samples = this.downsampler.push(block);
    this.onSamples?.(samples);
    for (const u of this.segmenter.push(samples)) this.emit(u);
    this.level = this.segmenter.level;
  }

  private emit(u: Utterance): void {
    this.onUtterance({ ...u, startMs: Math.round(u.startMs + this.offsetBaseMs) });
  }

  /** Stops audio processing and the underlying tracks; emits the last utterance. */
  async stop(): Promise<void> {
    for (const u of this.segmenter.flush()) this.emit(u);
    this.node?.port.close();
    this.source?.disconnect();
    this.node?.disconnect();
    this.stream.getTracks().forEach((t) => t.stop());
    if (this.ctx && this.ctx.state !== "closed") await this.ctx.close();
    this.ctx = null;
  }
}

export async function listMicrophones(): Promise<MediaDeviceInfo[]> {
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((d) => d.kind === "audioinput" && d.deviceId !== "default" && d.deviceId !== "communications");
}

/** Asks for microphone permission once so device labels become visible. */
export async function unlockDeviceLabels(): Promise<void> {
  const s = await navigator.mediaDevices.getUserMedia({ audio: true });
  s.getTracks().forEach((t) => t.stop());
}

export function openMicrophone(deviceId: string, noiseSuppression = true): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({
    // Browser processing: echo cancellation always (avoids re-capturing the speakers); its noise suppressor
    // follows the "Lọc tạp âm" setting and is complemented by our own chain (lib/audio/denoise.ts).
    audio: { deviceId: { exact: deviceId }, echoCancellation: true, noiseSuppression, autoGainControl: true },
  });
}

/**
 * System / tab audio through screen sharing. Chrome and Edge on Windows can
 * share "system audio" for a whole screen, or a tab's audio. The video track
 * is required by the API and stopped immediately.
 */
export async function openDisplayAudio(): Promise<MediaStream> {
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: true,
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    // Chromium hints (ignored elsewhere): offer the "share system audio" checkbox.
    systemAudio: "include",
    selfBrowserSurface: "exclude",
  } as DisplayMediaStreamOptions);
  stream.getVideoTracks().forEach((t) => t.stop());
  if (stream.getAudioTracks().length === 0) {
    stream.getTracks().forEach((t) => t.stop());
    throw new Error("NO_AUDIO_TRACK");
  }
  return new MediaStream(stream.getAudioTracks());
}
