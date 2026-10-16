import { describe, expect, it } from "vitest";
import { RealtimeEventProcessor, type FinalUtterance } from "./realtime-events";

function setup() {
  const interim: Record<string, string> = {};
  const finals: FinalUtterance[] = [];
  const errors: string[] = [];
  const p = new RealtimeEventProcessor({
    onInterim: (id, text) => (interim[id] = text),
    onFinal: (u) => finals.push(u),
    onError: (m) => errors.push(m),
  });
  const send = (ev: object) => p.handle(JSON.stringify(ev));
  return { p, interim, finals, errors, send };
}

describe("RealtimeEventProcessor", () => {
  it("streams interim words and emits the final utterance with timing", () => {
    const { p, interim, finals, send } = setup();
    p.baseMs = 10_000;
    send({ type: "input_audio_buffer.speech_started", item_id: "it1", audio_start_ms: 1200 });
    send({ type: "conversation.item.input_audio_transcription.delta", item_id: "it1", delta: "Xin " });
    expect(interim.it1).toBe("Xin ");
    send({ type: "conversation.item.input_audio_transcription.delta", item_id: "it1", delta: "chào" });
    expect(interim.it1).toBe("Xin chào");
    send({ type: "input_audio_buffer.speech_stopped", item_id: "it1", audio_end_ms: 3500 });
    send({ type: "conversation.item.input_audio_transcription.completed", item_id: "it1", transcript: "Xin chào, tôi là Hùng." });
    expect(interim.it1).toBe("");
    expect(finals).toEqual([{ itemId: "it1", text: "Xin chào, tôi là Hùng.", startMs: 11_200, durationMs: 2300, speaker: null }]);
  });

  it("uses the dominant speaker label from segment events", () => {
    const { finals, send } = setup();
    send({ type: "conversation.item.input_audio_transcription.segment", item_id: "a", speaker: "spk_1", text: "long text here" });
    send({ type: "conversation.item.input_audio_transcription.segment", item_id: "a", speaker: "spk_2", text: "ok" });
    send({ type: "conversation.item.input_audio_transcription.completed", item_id: "a", transcript: "long text here ok" });
    expect(finals[0].speaker).toBe("spk_1");
  });

  it("ignores empty finals, malformed messages and unknown events; reports errors", () => {
    const { p, finals, errors, send } = setup();
    p.handle("not json");
    send({ type: "session.created" });
    send({ type: "conversation.item.input_audio_transcription.completed", item_id: "x", transcript: "   " });
    send({ type: "conversation.item.input_audio_transcription.failed", item_id: "y", error: { message: "bad audio" } });
    send({ type: "error", error: { message: "invalid session" } });
    expect(finals).toHaveLength(0);
    expect(errors).toEqual(["bad audio", "invalid session"]);
  });

  it("falls back to the capture clock when no timestamps are sent", () => {
    const { p, finals, send } = setup();
    let now = 5000;
    p.now = () => now;
    send({ type: "conversation.item.input_audio_transcription.delta", item_id: "z", delta: "Hi" });
    now = 6000;
    send({ type: "conversation.item.input_audio_transcription.completed", item_id: "z", transcript: "Hi there" });
    expect(finals[0].startMs).toBe(5000);
    expect(finals[0].durationMs).toBeNull();
  });
});
