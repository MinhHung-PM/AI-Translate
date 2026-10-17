/**
 * Pure handler for OpenAI Realtime *Translation* events (gpt-realtime-translate,
 * data channel "oai-events"). Per openai/openai-openapi and the OpenAI cookbook
 * "Build Live Translation Apps with gpt-realtime-translate":
 *   session.input_transcript.delta  {delta, elapsed_ms}  source-language words
 *   session.output_transcript.delta {delta, elapsed_ms}  translated words
 *   session.output_audio.delta / session.created / session.updated / session.closed
 *   error {error: {message}}
 * Deltas are append-only: there are no items and no "completed" event, so the
 * browser cuts the stream into sentences itself — after a pause (no new words
 * for `idleMs`) or at a sentence end once a bubble gets long.
 */
import type { FinalUtterance, RealtimeHandlers } from "./realtime-events";

const SENTENCE_END = /[.!?。！？…]\s*$/;

export class TranslationEventProcessor {
  private original = "";
  private translation = "";
  private startMs: number | null = null;
  private lastAt = 0;
  private seq = 0;
  private itemId = "";
  /** Capture-clock time (ms) at which this connection's audio started. */
  baseMs = 0;
  now: () => number = () => this.baseMs;
  /** A bubble longer than this is closed at the next sentence end. */
  maxChars = 160;

  constructor(private readonly h: RealtimeHandlers) {}

  handle(raw: string): void {
    let ev: { type?: string; delta?: unknown; elapsed_ms?: unknown; error?: { message?: string } };
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
    if (typeof ev.delta !== "string" || !ev.delta) return;
    const now = this.now();
    if (this.startMs === null) {
      const elapsed = typeof ev.elapsed_ms === "number" ? ev.elapsed_ms : null;
      // elapsed_ms marks the end of the audio window that produced the words.
      this.startMs = Math.max(0, Math.round(elapsed !== null ? Math.min(this.baseMs + elapsed, now) : now) - 1000);
      this.itemId = `tr-${Math.round(this.baseMs)}-${++this.seq}`;
    }
    if (input) this.original += ev.delta;
    else this.translation += ev.delta;
    this.lastAt = now;
    this.h.onInterim(this.itemId, this.original.trim(), this.translation.trim());
    if (!input && this.translation.length >= this.maxChars && SENTENCE_END.test(this.translation)) this.cut();
  }

  /** Close the current bubble when no words arrived for `idleMs` (speaker paused). */
  flushIdle(idleMs: number): void {
    if (this.startMs === null) return;
    // The interpreter waits for context, so its words can trail the speaker: give an
    // unfinished translation longer before closing the bubble.
    const wait = idleMs && !SENTENCE_END.test(this.translation) ? idleMs * 2 : idleMs;
    if (this.now() - this.lastAt >= wait) this.cut();
  }

  private cut(): void {
    if (this.startMs === null) return;
    const u: FinalUtterance = {
      itemId: this.itemId,
      text: this.original.trim(),
      translation: this.translation.trim(),
      startMs: this.startMs,
      durationMs: Math.max(0, Math.round(this.lastAt - this.startMs)),
      speaker: null,
    };
    this.original = "";
    this.translation = "";
    this.startMs = null;
    this.h.onInterim(u.itemId, "", "");
    if (u.text || u.translation) this.h.onFinal(u);
  }
}
