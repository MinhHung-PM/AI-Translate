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
  const src = (delta: string) => p.handle(JSON.stringify({ type: "session.input_transcript.delta", delta }));
  const out = (delta: string) => p.handle(JSON.stringify({ type: "session.output_transcript.delta", delta }));
  const tick = (ms: number) => {
    clock += ms;
    p.flushIdle(1300);
  };
  const pairs = () => finals.map((f) => [f.text, f.translation]);
  return { p, interim, finals, errors, src, out, tick, pairs };
}

describe("TranslationEventProcessor", () => {
  it("pairs each translated sentence with its own source sentence", () => {
    const { src, out, tick, pairs, interim, finals } = setup();
    src("本日の");
    tick(300);
    out("Chủ đề ");
    src("議題です。");
    tick(300);
    expect(interim.at(-1)).toEqual({ text: "本日の議題です。", translation: "Chủ đề" });
    src("次に");
    out("hôm nay.");
    expect(pairs()).toEqual([["本日の議題です。", "Chủ đề hôm nay."]]);
    expect(finals[0].startMs).toBe(10_000);
    tick(300);
    src("予算を確認します。");
    tick(300);
    out("Tiếp theo xác nhận ngân sách.");
    expect(pairs()).toEqual([
      ["本日の議題です。", "Chủ đề hôm nay."],
      ["次に予算を確認します。", "Tiếp theo xác nhận ngân sách."],
    ]);
    expect(finals[0].itemId).not.toBe(finals[1].itemId);
  });

  it("waits for a source transcript that arrives after its translation (the reported bug)", () => {
    const { src, out, tick, pairs } = setup();
    out("まず、T1のパートを見ていきます。"); // translation first: the source is not there yet
    tick(500);
    expect(pairs()).toEqual([]);
    src("Đầu tiên chúng ta xem phần của team 1.");
    expect(pairs()).toEqual([["Đầu tiên chúng ta xem phần của team 1.", "まず、T1のパートを見ていきます。"]]);
  });

  it("never copies the translation into the source when the source never arrives", () => {
    const { out, tick, finals } = setup();
    out("Xin chào mọi người.");
    tick(1300);
    tick(1400);
    expect(finals).toHaveLength(1);
    expect(finals[0]).toMatchObject({ text: "", translation: "Xin chào mọi người." });
  });

  it("keeps a fast speaker's next sentence for the next translation", () => {
    const { src, out, tick, pairs } = setup();
    src("一つ目の文です。");
    tick(200);
    out("Đây là ");
    tick(200);
    src("二つ目の文です。"); // speaker is already one sentence ahead
    tick(200);
    out("câu thứ nhất.");
    expect(pairs()).toEqual([["一つ目の文です。", "Đây là câu thứ nhất."]]);
    out("Đây là câu thứ hai.");
    expect(pairs().at(-1)).toEqual(["二つ目の文です。", "Đây là câu thứ hai."]);
  });

  it("keeps short source sentences the interpreter merged into one translation", () => {
    const { src, out, tick, pairs } = setup();
    src("はい。");
    tick(300);
    src("わかりました。");
    tick(400);
    out("Vâng, tôi hiểu rồi.");
    expect(pairs()).toEqual([["はい。 わかりました。", "Vâng, tôi hiểu rồi."]]);
  });

  it("emits source sentences that get no translation (already in the target language)", () => {
    const { src, tick, finals } = setup();
    src("Vâng, tôi đồng ý");
    tick(1600); // pause closes the unpunctuated sentence
    expect(finals).toHaveLength(0);
    tick(1400);
    tick(1400);
    expect(finals).toHaveLength(1);
    expect(finals[0]).toMatchObject({ text: "Vâng, tôi đồng ý", translation: "" });
  });

  it("closes an unpunctuated translation after a pause and flushes everything on stop", () => {
    const { p, src, out, tick, pairs } = setup();
    src("確認お願いします");
    out("Nhờ anh xác nhận giúp");
    tick(1400); // the translation closed; its source closes a moment later
    tick(300);
    expect(pairs()).toEqual([["確認お願いします", "Nhờ anh xác nhận giúp"]]);
    src("最後に");
    out("Cuối cùng");
    p.flushIdle(0);
    expect(pairs().at(-1)).toEqual(["最後に", "Cuối cùng"]);
  });

  it("takes the original words from the companion transcription session (audit trail)", () => {
    const { p, src, out, tick, pairs, interim } = setup();
    p.externalSource = true;
    src("ignored: the interpreter's own source transcript");
    p.setSourceInterim("Đầu tiên chúng ta");
    out("まず、");
    expect(interim.at(-1)).toEqual({ text: "Đầu tiên chúng ta", translation: "まず、" });
    out("チーム1のパートを見ていきます。"); // translation done before the source sentence is final
    tick(400);
    expect(pairs()).toEqual([]);
    p.addSource("Đầu tiên chúng ta xem phần của team 1.", 10_100);
    expect(pairs()).toEqual([["Đầu tiên chúng ta xem phần của team 1.", "まず、チーム1のパートを見ていきます。"]]);
    p.addSource("Vâng.", 12_000); // same-language reply: no translation comes
    tick(1300);
    tick(1300);
    tick(1300);
    tick(1300);
    expect(pairs().at(-1)).toEqual(["Vâng.", ""]);
  });

  it("reports errors and ignores audio / malformed events", () => {
    const { p, errors, finals } = setup();
    p.handle(JSON.stringify({ type: "error", error: { message: "boom" } }));
    p.handle(JSON.stringify({ type: "session.output_audio.delta", delta: "AAAA" }));
    p.handle("not json");
    p.handle(JSON.stringify({ type: "session.output_transcript.delta", delta: 42 }));
    expect(errors).toEqual(["boom"]);
    expect(finals).toHaveLength(0);
  });
});
