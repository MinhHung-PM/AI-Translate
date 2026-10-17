// AudioWorklet: adaptive noise gate (downward expander) for meeting audio.
// Learns the background-noise floor (minimum frame level over ~3 s) and
// attenuates audio that stays near it, with attack/hold/release smoothing so
// words are not clipped. Runs before speech recognition; nothing is recorded.
// Shared with unit tests (src/lib/audio/noise-gate.test.ts loads this file).

const PRESETS = {
  standard: { ratio: 2.5, floorGain: 0.12, attackMs: 4, holdMs: 250, releaseMs: 180, minThreshold: 0.004 },
  strong: { ratio: 3.5, floorGain: 0.03, attackMs: 3, holdMs: 180, releaseMs: 120, minThreshold: 0.006 },
};

class NoiseGateCore {
  constructor(sampleRate, preset) {
    const p = PRESETS[preset] || PRESETS.standard;
    this.p = p;
    this.rate = sampleRate;
    this.levels = [];
    this.window = Math.round((3 * sampleRate) / 128); // ~3 s of 128-sample blocks
    this.noise = 0.003;
    this.gain = 1;
    this.holdLeft = 0;
    this.attackCoef = Math.exp(-1 / ((p.attackMs / 1000) * sampleRate));
    this.releaseCoef = Math.exp(-1 / ((p.releaseMs / 1000) * sampleRate));
    this.holdSamples = Math.round((p.holdMs / 1000) * sampleRate);
    this.open = true;
  }

  get threshold() {
    return Math.max(this.p.minThreshold, this.noise * this.p.ratio);
  }

  /** Processes one block in place; returns the block's input RMS. */
  process(block) {
    let sum = 0;
    for (let i = 0; i < block.length; i++) sum += block[i] * block[i];
    const level = Math.sqrt(sum / Math.max(1, block.length));
    this.levels.push(level);
    if (this.levels.length > this.window) this.levels.shift();
    if (this.levels.length >= 20) this.noise = Math.min.apply(null, this.levels);

    if (level > this.threshold) {
      this.open = true;
      this.holdLeft = this.holdSamples;
    } else if (this.holdLeft > 0) {
      this.holdLeft -= block.length;
    } else {
      this.open = false;
    }
    const target = this.open ? 1 : this.p.floorGain;
    for (let i = 0; i < block.length; i++) {
      const coef = target > this.gain ? this.attackCoef : this.releaseCoef;
      this.gain = target + (this.gain - target) * coef;
      block[i] *= this.gain;
    }
    return level;
  }
}

if (typeof AudioWorkletProcessor !== "undefined") {
  class NoiseGateProcessor extends AudioWorkletProcessor {
    constructor(options) {
      super();
      this.core = new NoiseGateCore(sampleRate, (options.processorOptions || {}).preset);
      this.frames = 0;
    }
    process(inputs, outputs) {
      const input = inputs[0];
      const output = outputs[0];
      if (!input || !input.length) return true;
      const n = input[0].length;
      const mono = new Float32Array(n);
      for (let c = 0; c < input.length; c++) for (let i = 0; i < n; i++) mono[i] += input[c][i] / input.length;
      this.core.process(mono);
      for (let c = 0; c < output.length; c++) output[c].set(mono);
      if ((this.frames += n) >= sampleRate / 10) {
        this.frames = 0;
        this.port.postMessage({ open: this.core.open, gain: this.core.gain, noise: this.core.noise });
      }
      return true;
    }
  }
  registerProcessor("noise-gate", NoiseGateProcessor);
}

if (typeof globalThis !== "undefined") globalThis.__NoiseGateCore = NoiseGateCore;
