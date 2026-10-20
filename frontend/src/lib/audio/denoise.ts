"use client";

export type NoiseLevel = "off" | "standard" | "strong";

export interface DenoisedSource {
  /** Cleaned stream: fed to speech recognition (streaming and per-sentence). */
  stream: MediaStream;
  /** True while the gate is letting speech through (for the UI indicator). */
  gateOpen: () => boolean;
  close: () => Promise<void>;
}

const GATE_URL = "/audio-worklets/noise-gate.js";

/**
 * Noise suppression chain (Web Audio), applied before recognition. Stacked suppressors (browser +
 * gate + provider) clip soft syllables and word endings — Vietnamese tones and final consonants
 * suffer first — so the levels add processing gradually:
 *   standard: high-pass 90 Hz only (hum, air-con, desk rumble); the browser's own noise suppression
 *             (microphones) does the rest
 *   strong:   + low-pass 7.5 kHz (hiss) + adaptive noise gate (public/audio-worklets/noise-gate.js),
 *             and the provider's noise reduction (server side)
 * "off" returns the original stream untouched.
 */
export async function denoise(input: MediaStream, level: NoiseLevel, kind: "microphone" | "other" = "microphone"): Promise<DenoisedSource> {
  if (level === "off") {
    return { stream: input, gateOpen: () => true, close: async () => input.getTracks().forEach((t) => t.stop()) };
  }
  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule(GATE_URL);
  const src = ctx.createMediaStreamSource(input);
  const hp = ctx.createBiquadFilter();
  hp.type = "highpass";
  hp.frequency.value = 90;
  hp.Q.value = 0.7;
  const lp = ctx.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = level === "strong" ? 7500 : 20000; // effectively off below "strong"
  lp.Q.value = 0.7;
  // The gate swallows quiet speech and word endings: only for "strong" (noisy rooms).
  void kind;
  const useGate = level === "strong";
  const gate = new AudioWorkletNode(ctx, "noise-gate", {
    numberOfInputs: 1,
    numberOfOutputs: 1,
    outputChannelCount: [1],
    processorOptions: { preset: useGate ? level : "bypass" },
  });
  let open = true;
  gate.port.onmessage = (ev: MessageEvent<{ open: boolean }>) => {
    open = ev.data.open;
  };
  const dest = ctx.createMediaStreamDestination();
  src.connect(hp).connect(lp).connect(gate).connect(dest);
  if (ctx.state === "suspended") await ctx.resume();
  return {
    stream: dest.stream,
    gateOpen: () => open,
    close: async () => {
      gate.port.close();
      src.disconnect();
      input.getTracks().forEach((t) => t.stop());
      dest.stream.getTracks().forEach((t) => t.stop());
      if (ctx.state !== "closed") await ctx.close();
    },
  };
}
