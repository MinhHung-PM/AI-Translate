// AudioWorklet: mixes input channels to mono and forwards 128-sample blocks to the page.
// Served from the app's own origin so the Content-Security-Policy stays 'self'-only.
class MonoTap extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input.length) {
      const n = input[0].length;
      const out = new Float32Array(n);
      for (let c = 0; c < input.length; c++) {
        const ch = input[c];
        for (let i = 0; i < n; i++) out[i] += ch[i] / input.length;
      }
      this.port.postMessage(out, [out.buffer]);
    }
    return true;
  }
}
registerProcessor("mono-tap", MonoTap);
