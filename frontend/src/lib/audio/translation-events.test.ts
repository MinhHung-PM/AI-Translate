import { describe, expect, it } from "vitest";
import type { FinalUtterance } from "./realtime-events";
import { TranslationEventProcessor } from "./translation-events";

function setup() {
  let clock = 10_000;
  const interim: { text: string; translation?: string }[] = [];
  const finals: FinalUtterance[] = [];
  const errors: string[] = [];
  const p = new TranslationEventProcessor({
    onInterim: (_id, text, translation) => interim.push({ text, translation }),
    onFinal: (u) => finals.push(u),
    onError: (m) => errors.push(m),
  });
  p.baseMs = 10_000;
  p.now = () => clock;
  const send = (ev: object) => p.handle(JSON.stringify(ev));
  const tick = (ms: number) => (clock += ms);
  return { p, interim, finals, errors, send, tick };
}

describe("TranslationEventProcessor", () => {
  it("streams translated words with the original and closes the bubble after a pause", () => {
    const { p, interim, finals, send, tick } = setup();
    tick(1400);
    send({ type: "session.input_transcript.delta", delta: "本日の", elapsed_ms: 1400 });
    tick(200);
    send({ type: "session.output_transcript.delta", delta: "Chủ đề ", elapsed_ms: 1600 });
    tick(200);
    send({ type: "session.input_transcript.delta", delta: "議題です。", elapsed_ms: 1800 });
    send({ type: "session.output_transcript.delta", delta: "hôm nay.", elapsed_ms: 1800 });
    expect(interim.at(-1)).toEqual({ text: "本日の議題です。", translation: "Chủ đề hôm nay." });
    send({ type: "session.output_audio.delta", delta: "AAAA" }); // translated speech: not text
    tick(1000);
    p.flushIdle(1300);
    expect(finals).toHaveLength(0);
    tick(400);
    p.flushIdle(1300);
    expect(finals).toEqual([
      { itemId: expect.stringMatching(/^tr-/), text: "本日の議題です。", translation: "Chủ đề hôm nay.", startMs: 10_400, durationMs: 1400, speaker: null },
    ]);
    expect(interim.at(-1)).toEqual({ text: "", translation: "" });
    // The next sentence gets a new id.
    send({ type: "session.output_transcript.delta", delta: "Tiếp theo", elapsed_ms: 5000 });
    p.flushIdle(0);
    expect(finals[1].itemId).not.toBe(finals[0].itemId);
    expect(finals[1]).toMatchObject({ text: "", translation: "Tiếp theo" });
  });

  it("waits longer when the translation is mid-sentence (interpreter trails the speaker)", () => {
    const { p, finals, send, tick } = setup();
    send({ type: "session.input_transcript.delta", delta: "Let's review the plan", elapsed_ms: 0 });
    send({ type: "session.output_transcript.delta", delta: "Hãy cùng xem", elapsed_ms: 200 });
    tick(1500);
    p.flushIdle(1300);
    expect(finals).toHaveLength(0);
    tick(1200);
    p.flushIdle(1300);
    expect(finals).toHaveLength(1);
  });

  it("splits long speech at sentence ends and reports errors", () => {
    const { p, finals, errors, send } = setup();
    p.maxChars = 20;
    send({ type: "session.output_transcript.delta", delta: "Câu thứ nhất khá là dài." });
    expect(finals).toHaveLength(1);
    send({ type: "session.output_transcript.delta", delta: "Câu hai" });
    expect(finals).toHaveLength(1);
    send({ type: "error", error: { message: "boom" } });
    p.handle("not json");
    send({ type: "session.output_transcript.delta", delta: 42 });
    expect(errors).toEqual(["boom"]);
  });
});
