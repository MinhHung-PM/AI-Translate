/** Regression: a reconnect scheduled before Stop must not open a connection after Stop. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { RealtimeCaptionSource } from "./realtime";
import { SonioxCaptionSource } from "./soniox";

const g = globalThis as unknown as Record<string, unknown>;
const noop = { onInterim() {}, onFinal() {}, onError() {} };

afterEach(() => {
  vi.useRealTimers();
});

describe("stop during a pending reconnect", () => {
  it("OpenAI: no new token or peer connection after stop()", async () => {
    vi.useFakeTimers();
    const pcs: { closed: boolean; connectionState: string; onconnectionstatechange: (() => void) | null }[] = [];
    g.RTCPeerConnection = class {
      closed = false;
      connectionState = "new";
      onconnectionstatechange: (() => void) | null = null;
      ontrack = null;
      constructor() {
        pcs.push(this);
      }
      addTrack() {}
      createDataChannel() {
        return { readyState: "connecting", send() {} };
      }
      async createOffer() {
        return { sdp: "x" };
      }
      async setLocalDescription() {}
      async setRemoteDescription() {}
      close() {
        this.closed = true;
      }
    };
    g.fetch = async () => ({ ok: true, text: async () => "answer" });
    const getToken = vi.fn(async () => ({ client_secret: "s", expires_at: 0, model: "m", calls_url: "u" }));
    const rt = new RealtimeCaptionSource({ getAudioTracks: () => [] } as unknown as MediaStream, getToken, noop, () => 0, () => {});
    await rt.start();
    pcs[0].connectionState = "disconnected";
    pcs[0].onconnectionstatechange!(); // reconnect: waits 1 s
    await rt.stop();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(getToken).toHaveBeenCalledTimes(1);
    expect(pcs.every((pc) => pc.closed)).toBe(true);
  });

  it("Soniox: no new socket or timers after stop()", async () => {
    vi.useFakeTimers();
    const sockets: { readyState: number; onclose: () => void }[] = [];
    g.WebSocket = class {
      static OPEN = 1;
      readyState = 0;
      binaryType = "";
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onclose: (() => void) | null = null;
      onmessage = null;
      constructor() {
        sockets.push(this as never);
        setTimeout(() => {
          this.readyState = 1;
          this.onopen?.();
        }, 10);
      }
      send() {}
      close() {
        this.readyState = 3;
      }
    };
    const getToken = vi.fn(async () => ({ client_secret: "s", expires_at: 0, model: "m", calls_url: "u", kind: "soniox" as const, session_config: {} }));
    const sx = new SonioxCaptionSource({ onSamples: null } as never, getToken, noop, () => 0, () => {}, false);
    const started = sx.start();
    await vi.advanceTimersByTimeAsync(20);
    await started;
    sockets[0].readyState = 3;
    sockets[0].onclose(); // dropped: reconnect waits 1 s
    await sx.stop();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(getToken).toHaveBeenCalledTimes(1);
    expect(sockets).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});
