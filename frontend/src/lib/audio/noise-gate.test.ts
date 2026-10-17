import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Load the real worklet file (single source of truth) outside the browser.
interface Core {
  process(block: Float32Array): number;
  open: boolean;
  noise: number;
  threshold: number;
}
type CoreCtor = new (rate: number, preset: string) => Core;
const src = readFileSync(path.resolve(__dirname, "../../../public/audio-worklets/noise-gate.js"), "utf8");
new Function(src)();
const NoiseGateCore = (globalThis as unknown as { __NoiseGateCore: CoreCtor }).__NoiseGateCore;

const RATE = 48000;
function run(core: Core, gen: (i: number) => number, ms: number): Float32Array {
  const n = Math.round((RATE * ms) / 1000 / 128) * 128;
  const out = new Float32Array(n);
  for (let off = 0; off < n; off += 128) {
    const block = Float32Array.from({ length: 128 }, (_, k) => gen(off + k));
    core.process(block);
    out.set(block, off);
  }
  return out;
}
const rms = (x: Float32Array) => Math.sqrt(x.reduce((s, v) => s + v * v, 0) / x.length);
let seed = 1;
const noise = (amp: number) => () => {
  seed = (seed * 16807) % 2147483647;
  return amp * ((seed / 2147483647) * 2 - 1);
};
const voice = (amp: number) => (i: number) => amp * Math.sin((2 * Math.PI * 220 * i) / RATE) * (0.6 + 0.4 * Math.sin((2 * Math.PI * 4 * i) / RATE));

describe("noise gate worklet", () => {
  it("learns the noise floor and attenuates background noise between words", () => {
    const core = new NoiseGateCore(RATE, "standard");
    const out = run(core, noise(0.02), 4000);
    const tail = out.slice(out.length - RATE); // last second, after adaptation
    expect(rms(tail)).toBeLessThan(0.02 * 0.6 * 0.3); // > ~10 dB quieter than the input noise
    expect(core.open).toBe(false);
  });

  it("passes speech over the noise almost unchanged", () => {
    const core = new NoiseGateCore(RATE, "standard");
    run(core, noise(0.02), 3000);
    const n = noise(0.02);
    const v = voice(0.25);
    const n2 = noise(0.02);
    const input = Float32Array.from({ length: RATE * 1.5 }, (_, i) => v(i) + n2());
    const speech = run(core, (i) => v(i) + n(), 1500);
    const settled = speech.slice(Math.round(RATE * 0.05));
    // Speech level preserved: within ~0.5 dB of the input.
    expect(rms(settled)).toBeGreaterThan(rms(input) * 0.94);
  });

  it("strong preset suppresses more than standard", () => {
    const a = new NoiseGateCore(RATE, "standard");
    const b = new NoiseGateCore(RATE, "strong");
    const ra = rms(run(a, noise(0.02), 4000).slice(-RATE));
    seed = 1;
    const rb = rms(run(b, noise(0.02), 4000).slice(-RATE));
    expect(rb).toBeLessThan(ra);
  });

  it("does not clip the start of a word (hold + fast attack)", () => {
    const core = new NoiseGateCore(RATE, "strong");
    run(core, () => 0.001, 3000);
    const v = voice(0.3);
    const onset = run(core, v, 30); // first 30 ms of speech
    expect(rms(onset)).toBeGreaterThan(0.1);
  });
});

describe("noise gate bypass (meeting/tab audio in standard mode)", () => {
  it("passes audio unchanged", () => {
    const core = new NoiseGateCore(RATE, "bypass");
    const out = run(core, noise(0.02), 4000);
    expect(rms(out.slice(-RATE))).toBeGreaterThan(0.02 * 0.5);
  });
});
