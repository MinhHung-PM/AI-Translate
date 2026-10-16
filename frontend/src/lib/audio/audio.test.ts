import { describe, expect, it } from "vitest";
import { Downsampler } from "./resample";
import { UtteranceSegmenter } from "./segmenter";
import { encodeWav, rms } from "./wav";

const RATE = 16000;
const tone = (ms: number, amp = 0.3, freq = 220) =>
  Float32Array.from({ length: Math.round((RATE * ms) / 1000) }, (_, i) => amp * Math.sin((2 * Math.PI * freq * i) / RATE));
const silence = (ms: number, amp = 0.001) => Float32Array.from({ length: Math.round((RATE * ms) / 1000) }, (_, i) => (i % 2 ? amp : -amp));
function join(...parts: Float32Array[]): Float32Array {
  const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}
/** Speech-like signal: syllables (300 ms) separated by short quiet gaps (90 ms). */
function speech(ms: number): Float32Array {
  const parts: Float32Array[] = [];
  for (let t = 0; t < ms; t += 390) parts.push(tone(300), silence(90));
  return join(...parts);
}

describe("Downsampler", () => {
  it("converts 48 kHz to 16 kHz across block boundaries", () => {
    const ds = new Downsampler(48000, 16000);
    let n = 0;
    for (let b = 0; b < 100; b++) n += ds.push(new Float32Array(128).fill(0.5)).length;
    expect(Math.abs(n - (100 * 128) / 3)).toBeLessThanOrEqual(1);
    expect(ds.push(new Float32Array(3).fill(0.5))[0]).toBeCloseTo(0.5);
  });
  it("handles non-integer ratios (44.1 kHz)", () => {
    const ds = new Downsampler(44100, 16000);
    const out = ds.push(new Float32Array(44100));
    expect(Math.abs(out.length - 16000)).toBeLessThanOrEqual(1);
  });
});

describe("encodeWav", () => {
  it("writes a valid 16-bit mono PCM header", () => {
    const wav = encodeWav(Float32Array.from([0, 1, -1, 0.5]), RATE);
    const v = new DataView(wav.buffer);
    expect(String.fromCharCode(...wav.slice(0, 4))).toBe("RIFF");
    expect(String.fromCharCode(...wav.slice(8, 12))).toBe("WAVE");
    expect(v.getUint16(22, true)).toBe(1);
    expect(v.getUint32(24, true)).toBe(RATE);
    expect(v.getUint16(34, true)).toBe(16);
    expect(v.getUint32(40, true)).toBe(8);
    expect(v.getInt16(46, true)).toBe(32767);
    expect(v.getInt16(48, true)).toBe(-32768);
    expect(wav.length).toBe(52);
  });
  it("computes RMS", () => {
    expect(rms(new Float32Array([0.5, -0.5]))).toBeCloseTo(0.5);
  });
});

describe("UtteranceSegmenter", () => {
  it("splits speech on silence and reports start offsets", () => {
    const seg = new UtteranceSegmenter();
    const utts = seg.push(join(silence(1000), tone(1200), silence(1000), tone(800), silence(1000)));
    expect(utts).toHaveLength(2);
    expect(utts[0].startMs).toBeGreaterThan(700);
    expect(utts[0].startMs).toBeLessThan(1000);
    expect(utts[0].durationMs).toBeGreaterThan(1200);
    expect(utts[1].startMs).toBeGreaterThan(2900);
  });
  it("ignores short clicks and caps long monologues", () => {
    const seg = new UtteranceSegmenter({ maxUtteranceMs: 3000 });
    expect(seg.push(join(silence(500), tone(90), silence(1500)))).toHaveLength(0);
    const long = seg.push(join(speech(7000), silence(1000)));
    expect(long.length).toBeGreaterThanOrEqual(2);
    expect(Math.max(...long.map((u) => u.durationMs))).toBeLessThanOrEqual(3030);
    // Nothing is lost when a long utterance is split.
    const total = long.reduce((n, u) => n + u.durationMs, 0);
    expect(total).toBeGreaterThanOrEqual(7000);
  });
  it("flushes the utterance in progress and adapts to background noise", () => {
    const seg = new UtteranceSegmenter();
    seg.push(join(silence(2000, 0.02), tone(600, 0.3)));
    expect(seg.threshold).toBeGreaterThan(0.02);
    expect(seg.flush()).toHaveLength(1);
    expect(seg.flush()).toHaveLength(0);
  });
  it("splits long speech at a pause between words, not mid-syllable", () => {
    const seg = new UtteranceSegmenter({ maxUtteranceMs: 3000 });
    const utts = seg.push(join(silence(500), speech(6000), silence(1000)));
    // Each cut lands in a 90 ms gap: the next utterance starts with a (quiet) gap frame or a syllable onset.
    for (const u of utts.slice(0, -1)) {
      const tail = u.samples.slice(-Math.round(RATE * 0.03));
      expect(rms(tail)).toBeLessThan(0.05);
    }
  });
  it("does not trigger on steady background noise", () => {
    const seg = new UtteranceSegmenter();
    expect(seg.push(silence(5000, 0.004))).toHaveLength(0);
  });
  it("treats sustained background music as noise but still detects speech over it", () => {
    const seg = new UtteranceSegmenter();
    const hum = (ms: number) => tone(ms, 0.03, 60);
    const first = seg.push(hum(6000));
    expect(first.length).toBeLessThanOrEqual(1); // at most the initial burst before the floor adapts
    const mixed = speech(1500).map((x, i) => x + 0.03 * Math.sin((2 * Math.PI * 60 * i) / RATE));
    expect(seg.push(join(mixed, hum(1500)))).toHaveLength(1);
  });
});
