/**
 * Pure handler for OpenAI Realtime *Translation* events (gpt-realtime-translate,
 * data channel "oai-events"). Per openai/openai-openapi and the OpenAI cookbook
 * "Build Live Translation Apps with gpt-realtime-translate":
 *   session.input_transcript.delta  {delta, elapsed_ms}  source-language words
 *   session.output_transcript.delta {delta, elapsed_ms}  translated words
 *   session.output_audio.delta / session.created / session.updated / session.closed
 *   error {error: {message}}
 * Deltas are append-only, with no items and no "completed" event, and the two streams are
 * independent: the interpreter trails the speaker by a few seconds, and the source transcript
 * can arrive before or after its translation. Cutting both streams at the same pause pairs a
 * sentence with the wrong translation, so they are segmented separately:
 *   - source sentences end at sentence punctuation or after a short pause;
 *   - each finished translated sentence is paired with the oldest unpaired source sentence
 *     (plus any that are clearly stale), waiting briefly for the source if it has not arrived;
 *   - source sentences that never get a translation (speech already in the target language)
 *     are emitted on their own, and the server translates or keeps them.
 * A sentence whose source never arrived is emitted with empty `text` (shown as "no original").
 */
import type { RealtimeHandlers } from "./realtime-events";

const SENTENCE_END = /[.!?。！？…]["」』)）]?\s*$/;

interface Sentence {
  text: string;
  startAt: number;
  endAt: number;
}

export class TranslationEventProcessor {
  /** Source sentence being heard, and finished source sentences waiting for their translation. */
  private inCur: Sentence | null = null;
  private inDone: Sentence[] = [];
  /** Translated sentence being spoken, and a finished one waiting for its source. */
  private outCur: Sentence | null = null;
  private outWaiting: (Sentence & { since: number }) | null = null;
  private lastOutAt = 0;
  private seq = 0;
  private liveId = "";
  /** Source words from a separate transcription session (see addSource): the interpreter's own,
   * unreliable source transcript is then ignored. */
  externalSource = false;
  private sourceInterim = "";
  /** Capture-clock time (ms) at which this connection's audio started. */
  baseMs = 0;
  now: () => number = () => this.baseMs;

  constructor(private readonly h: RealtimeHandlers) {}

  handle(raw: string): void {
    let ev: { type?: string; delta?: unknown; error?: { message?: string } };
    try {
      ev = JSON.parse(raw);
    } catch {
      return;
    }
    if (ev.type === "error") {
      this.h.onError(ev.error?.message ?? "OpenAI Realtime error");
      return;
    }
    const input = ev.type === "session.input_transcript.delta";
    if (!input && ev.type !== "session.output_transcript.delta") return;
    if (input && this.externalSource) return;
    if (typeof ev.delta !== "string" || !ev.delta) return;
    const now = this.now();
    if (input) {
      this.inCur ??= { text: "", startAt: now, endAt: now };
      this.inCur.text += ev.delta;
      this.inCur.endAt = now;
      if (SENTENCE_END.test(this.inCur.text)) this.closeInput();
      if (this.outWaiting) this.pairWaiting(false); // its source may have just arrived
    } else {
      this.outCur ??= { text: "", startAt: now, endAt: now };
      this.outCur.text += ev.delta;
      this.outCur.endAt = now;
      this.lastOutAt = now;
      if (SENTENCE_END.test(this.outCur.text)) this.closeOutput();
    }
    this.emitInterim();
  }

  /**
   * Called a few times per second (``idleMs`` ≈ 1.3 s), and with 0 on stop to flush everything:
   * closes sentences whose stream went quiet and emits sentences that waited long enough.
   */
  flushIdle(idleMs: number): void {
    const force = idleMs === 0;
    const now = this.now();
    if (this.inCur && (force || now - this.inCur.endAt >= idleMs + 200)) this.closeInput();
    if (this.outCur && (force || now - this.outCur.endAt >= idleMs)) this.closeOutput();
    // A waiting translation pairs as soon as its source closed, or goes alone after a while.
    if (this.outWaiting) this.pairWaiting(force || now - this.outWaiting.since >= idleMs * 2);
    // Source sentences that got no translation at all (e.g. already in the target language).
    const quiet = !this.outCur && !this.outWaiting && (force || now - this.lastOutAt >= idleMs * 2);
    while (this.inDone.length && quiet && (force || now - this.inDone[0].endAt >= idleMs * 3)) {
      this.emit([this.inDone.shift()!], null);
    }
    this.emitInterim();
  }

  /** A finished source sentence from the companion transcription session (the original words). */
  addSource(text: string, startAt: number): void {
    if (!text.trim()) return;
    this.closeInput();
    this.inDone.push({ text, startAt, endAt: this.now() });
    this.sourceInterim = "";
    if (this.outWaiting) this.pairWaiting(false);
    this.emitInterim();
  }

  /** Words of the source sentence being spoken (companion session), for the live line. */
  setSourceInterim(text: string): void {
    this.sourceInterim = text;
    this.emitInterim();
  }

  private closeInput(): void {
    const s = this.inCur;
    this.inCur = null;
    if (s && s.text.trim()) this.inDone.push(s);
  }

  private closeOutput(): void {
    const s = this.outCur;
    this.outCur = null;
    if (!s || !s.text.trim()) return;
    if (this.outWaiting) this.pairWaiting(true); // never hold two translations
    this.outWaiting = { ...s, since: this.now() };
    this.pairWaiting(false);
  }

  /** Pair the waiting translation with its source; ``force`` emits it even without one. */
  private pairWaiting(force: boolean): void {
    const out = this.outWaiting;
    if (!out) return;
    if (!this.inDone.length && this.inCur && force) this.closeInput(); // partial source is better than none
    if (!this.inDone.length && !force) return; // the source transcript may still be on its way
    const sources = this.inDone.splice(0, 1);
    // Source sentences that ended well before this translation began were merged into it by the
    // interpreter (it often joins short sentences): keep them with it instead of drifting.
    while (this.inDone.length && this.inDone[0].endAt <= out.startAt) sources.push(this.inDone.shift()!);
    this.outWaiting = null;
    this.emit(sources, out);
  }

  private emit(sources: Sentence[], out: Sentence | null): void {
    const text = sources.map((s) => s.text.trim()).join(" ").trim();
    const translation = out?.text.trim() ?? "";
    if (!text && !translation) return;
    // The source's timing when there is one; a translation trails its speech by about a second.
    const startAt = sources.length ? Math.min(...sources.map((s) => s.startAt)) : (out?.startAt ?? 0) - 1000;
    const endAt = Math.max(...sources.map((s) => s.endAt), out?.endAt ?? 0);
    this.h.onFinal({
      itemId: `tr-${Math.round(this.baseMs)}-${++this.seq}`,
      text,
      translation,
      startMs: Math.max(0, Math.round(startAt)),
      durationMs: Math.max(0, Math.round(endAt - startAt)),
      speaker: null,
    });
  }

  /** One live line per source: unpaired source words + the translation being spoken. */
  private emitInterim(): void {
    const original = [...this.inDone.map((s) => s.text), this.inCur?.text ?? "", this.sourceInterim].join(" ").replace(/\s+/g, " ").trim();
    const translation = [this.outWaiting?.text ?? "", this.outCur?.text ?? ""].join(" ").replace(/\s+/g, " ").trim();
    if (original || translation) {
      this.liveId ||= `tr-live-${Math.round(this.baseMs)}`;
      this.h.onInterim(this.liveId, original, translation);
    } else if (this.liveId) {
      this.h.onInterim(this.liveId, "", "");
      this.liveId = "";
    }
  }
}
