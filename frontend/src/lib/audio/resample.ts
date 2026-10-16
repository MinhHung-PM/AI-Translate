/**
 * Streaming downsampler (e.g. 48 kHz → 16 kHz) by averaging the input samples
 * that fall into each output sample. Keeps the fractional position between
 * calls so consecutive AudioWorklet blocks join seamlessly.
 */
export class Downsampler {
  private pos = 0; // position of the next output sample, in input samples
  private acc = 0;
  private count = 0;
  private readonly ratio: number;

  constructor(
    readonly inRate: number,
    readonly outRate = 16000,
  ) {
    if (inRate < outRate) throw new Error("Input rate must be ≥ output rate");
    this.ratio = inRate / outRate;
  }

  push(input: Float32Array): Float32Array {
    const out: number[] = [];
    for (let i = 0; i < input.length; i++) {
      this.acc += input[i];
      this.count++;
      this.pos -= 1;
      if (this.pos <= 0) {
        out.push(this.acc / this.count);
        this.acc = 0;
        this.count = 0;
        this.pos += this.ratio;
      }
    }
    return Float32Array.from(out);
  }
}
