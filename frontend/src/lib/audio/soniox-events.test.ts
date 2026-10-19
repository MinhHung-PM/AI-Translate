import { describe, expect, it } from "vitest";
import type { FinalUtterance } from "./realtime-events";
import { SonioxEventProcessor } from "./soniox-events";

function setup(translating: boolean) {
  let clock = 5_000;
  const interim: { text: string; translation?: string }[] = [];
  const finals: FinalUtterance[] = [];
  const errors: string[] = [];
  const p = new SonioxEventProcessor(
    {
      onInterim: (_id, text, translation) => interim.push({ text, translation }),
      onFinal: (u) => finals.push(u),
      onError: (m) => errors.push(m),
    },
    translating,
  );
  p.baseMs = 5_000;
  p.now = () => clock;
  const send = (tokens: object[], extra: object = {}) => p.handle(JSON.stringify({ tokens, ...extra }));
  const tick = (ms: number) => (clock += ms);
  return { p, interim, finals, errors, send, tick };
}

const o = (text: string, is_final: boolean, start_ms?: number, end_ms?: number, speaker = "1") => ({
  text,
  is_final,
  start_ms,
  end_ms,
  speaker,
  translation_status: "original",
});
const tr = (text: string, is_final: boolean) => ({ text, is_final, translation_status: "translation" });

describe("SonioxEventProcessor", () => {
  it("streams original + translation and closes the sentence once the translation follows the endpoint", () => {
    const { interim, finals, send } = setup(true);
    send([o("前提", true, 1200, 1500), o("を確認", false)]);
    expect(interim.at(-1)).toEqual({ text: "前提を確認", translation: "" });
    send([o("を確認しましょう。", true, 1500, 2600), tr("Hãy xác", false), { text: "<end>", is_final: true }]);
    expect(interim.at(-1)).toEqual({ text: "前提を確認しましょう。", translation: "Hãy xác" });
    expect(finals).toHaveLength(0); // translation still pending
    send([tr("Hãy xác nhận giả định.", true)]);
    expect(finals).toEqual([
      {
        itemId: expect.stringMatching(/^sx-/),
        text: "前提を確認しましょう。",
        translation: "Hãy xác nhận giả định.",
        startMs: 6_200,
        durationMs: 1400,
        speaker: "1",
      },
    ]);
    expect(interim.at(-1)).toEqual({ text: "", translation: "" });
  });

  it("captions only: closes at the endpoint, keeps the main speaker, ignores markers", () => {
    const { finals, send } = setup(false);
    send([o("Xin chào ", true, 0, 400, "2"), o("mọi người", true, 400, 900, "2"), o("ạ", true, 900, 1000, "1")]);
    send([{ text: "<fin>", is_final: true }]);
    expect(finals).toHaveLength(0);
    send([{ text: "<end>", is_final: true }]);
    expect(finals[0]).toMatchObject({ text: "Xin chào mọi ngườiạ", translation: undefined, speaker: "2", startMs: 5_000 });
  });

  it("idle safety net flushes pending words; reports API errors", () => {
    const { p, finals, errors, send, tick } = setup(true);
    send([o("はい", false)]);
    tick(1000);
    p.flushIdle(2500);
    expect(finals).toHaveLength(0);
    tick(2000);
    p.flushIdle(2500);
    expect(finals[0]).toMatchObject({ text: "はい", translation: "" });
    send([], { error_code: 401, error_message: "Invalid or expired temporary API key." });
    p.handle("garbage");
    expect(errors).toEqual(["Invalid or expired temporary API key."]);
  });
});
