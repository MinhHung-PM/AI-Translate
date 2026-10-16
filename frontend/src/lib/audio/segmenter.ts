import { rms } from "./wav";

export interface Utterance {
  samples: Float32Array;
  /** Offset of the first sample from the start of the capture, in ms. */
  startMs: number;
  durationMs: number;
}

export interface SegmenterOptions {
  sampleRate?: number;
  frameMs?: number;
  /** Minimum voiced time for an utterance to be kept (filters clicks/coughs). */
  minSpeechMs?: number;
  /** Silence that ends an utterance. */
  endSilenceMs?: number;
  /** Hard cap: long monologues are cut so text appears quickly (server limit is 30 s). */
  maxUtteranceMs?: number;
  /** Audio kept before speech onset so the first syllable is not clipped. */
  preRollMs?: number;
  /** Absolute floor for the voice threshold (RMS, 0..1). */
  minThreshold?: number;
}

/**
 * Energy-based voice activity detection. The noise floor is the minimum frame
 * level over the last ~3 s (minimum statistics), so it adapts even when the
 * capture starts in a noisy room or with background music.
 * Feed 16 kHz mono samples; completed utterances are returned as they end.
 */
export class UtteranceSegmenter {
  private readonly rate: number;
  private readonly frame: number;
  private readonly o: Required<SegmenterOptions>;
  private pending = new Float32Array(0);
  private elapsedSamples = 0; // samples consumed into frames so far
  private noise = 0.003;
  private recentLevels: number[] = []; // last ~3 s of frame levels (minimum statistics)
  private preRoll: Float32Array[] = [];
  private current: Float32Array[] | null = null;
  private currentLevels: number[] = [];
  private currentStart = 0;
  private voicedMs = 0;
  private silenceMs = 0;
  /** Last frame level (0..1), for the UI meter. */
  level = 0;

  constructor(options: SegmenterOptions = {}) {
    this.o = {
      sampleRate: 16000,
      frameMs: 30,
      minSpeechMs: 500,
      endSilenceMs: 650,
      maxUtteranceMs: 12000,
      preRollMs: 240,
      minThreshold: 0.008,
      ...options,
    };
    this.rate = this.o.sampleRate;
    this.frame = Math.round((this.rate * this.o.frameMs) / 1000);
  }

  get threshold(): number {
    return Math.max(this.o.minThreshold, this.noise * 3);
  }

  push(samples: Float32Array): Utterance[] {
    const out: Utterance[] = [];
    const all = new Float32Array(this.pending.length + samples.length);
    all.set(this.pending);
    all.set(samples, this.pending.length);
    let i = 0;
    for (; i + this.frame <= all.length; i += this.frame) {
      const u = this.processFrame(all.slice(i, i + this.frame));
      if (u) out.push(u);
    }
    this.pending = all.slice(i);
    return out;
  }

  /** End of capture: emit the utterance in progress, if any. */
  flush(): Utterance[] {
    const u = this.current ? this.finish() : null;
    return u ? [u] : [];
  }

  private processFrame(frame: Float32Array): Utterance | null {
    const level = rms(frame);
    this.level = level;
    const frameStartMs = (this.elapsedSamples / this.rate) * 1000;
    this.elapsedSamples += frame.length;
    this.recentLevels.push(level);
    const window = Math.round(3000 / this.o.frameMs);
    if (this.recentLevels.length > window) this.recentLevels.shift();
    if (this.recentLevels.length >= 10) this.noise = Math.min(...this.recentLevels);
    const voiced = level > this.threshold;
    if (!this.current) {
      if (voiced) {
        const pre = this.preRoll;
        this.current = [...pre, frame];
        this.currentLevels = [...pre.map(() => 0), level];
        this.currentStart = frameStartMs - pre.length * this.o.frameMs;
        this.preRoll = [];
        this.voicedMs = this.o.frameMs;
        this.silenceMs = 0;
      } else {
        this.preRoll.push(frame);
        const maxPre = Math.ceil(this.o.preRollMs / this.o.frameMs);
        if (this.preRoll.length > maxPre) this.preRoll.shift();
      }
      return null;
    }
    this.current.push(frame);
    this.currentLevels.push(level);
    if (voiced) {
      this.voicedMs += this.o.frameMs;
      this.silenceMs = 0;
    } else {
      this.silenceMs += this.o.frameMs;
    }
    const durationMs = this.current.length * this.o.frameMs;
    if (this.silenceMs >= this.o.endSilenceMs) return this.finish();
    if (durationMs >= this.o.maxUtteranceMs) return this.splitAtQuietestPoint();
    return null;
  }

  /** Long monologue: cut at the quietest frame of the last ~2 s (a breath or a
   * pause between words) instead of mid-word; the rest starts the next utterance. */
  private splitAtQuietestPoint(): Utterance | null {
    const frames = this.current ?? [];
    const levels = this.currentLevels;
    const look = Math.min(frames.length - 1, Math.round(2000 / this.o.frameMs));
    let cut = frames.length;
    let best = Infinity;
    for (let i = frames.length - look; i < frames.length; i++) {
      if (levels[i] < best) {
        best = levels[i];
        cut = i + 1;
      }
    }
    const rest = frames.slice(cut);
    const restLevels = levels.slice(cut);
    this.current = frames.slice(0, cut);
    this.currentLevels = levels.slice(0, cut);
    const restStart = this.currentStart + cut * this.o.frameMs;
    const u = this.finish(true);
    if (rest.length) {
      this.current = rest;
      this.currentLevels = restLevels;
      this.currentStart = restStart;
      this.voicedMs = restLevels.filter((l) => l > this.threshold).length * this.o.frameMs;
    }
    return u;
  }

  private finish(forced = false): Utterance | null {
    const frames = this.current ?? [];
    this.current = null;
    this.currentLevels = [];
    const keep = forced || this.voicedMs >= this.o.minSpeechMs;
    this.voicedMs = 0;
    this.silenceMs = 0;
    if (!keep) return null;
    const total = frames.reduce((n, f) => n + f.length, 0);
    const samples = new Float32Array(total);
    let o = 0;
    for (const f of frames) {
      samples.set(f, o);
      o += f.length;
    }
    return { samples, startMs: Math.max(0, Math.round(this.currentStart)), durationMs: Math.round((total / this.rate) * 1000) };
  }
}
