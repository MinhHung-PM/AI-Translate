/**
 * Pure handler for Soniox real-time WebSocket responses (contract from Soniox's
 * official SDKs, see backend/app/audio/soniox.py):
 *   {tokens: [{text, start_ms, end_ms, is_final, speaker, language,
 *              translation_status: "original" | "translation" | "none"}],
 *    finished?, error_code?, error_message?}
 * Final tokens are appended once; non-final tokens are re-sent in full with every
 * message (they replace the previous ones). With endpoint detection the model emits
 * a final "<end>" token when the speaker finishes an utterance; translated tokens
 * for that utterance can follow shortly after, so a sentence is closed once the
 * endpoint is seen and nothing is pending (or after a quiet period, as a safety net).
 */
import type { RealtimeHandlers } from "./realtime-events";

interface SonioxToken {
  text?: string;
  start_ms?: number;
  end_ms?: number;
  is_final?: boolean;
  speaker?: string;
  translation_status?: "original" | "translation" | "none";
}

const MARKERS = new Set(["<end>", "<fin>"]);

export class SonioxEventProcessor {
  private original = "";
  private translation = "";
  private pendingOriginal = "";
  private pendingTranslation = "";
  private speakers: Record<string, number> = {};
  private firstMs: number | null = null;
  private lastMs: number | null = null;
  private endpoint = false;
  private lastAt = 0;
  private seq = 0;
  private itemId = "";
  /** Capture-clock time (ms) of the first audio sample sent on this connection. */
  baseMs = 0;
  now: () => number = () => this.baseMs;

  constructor(
    private readonly h: RealtimeHandlers,
    /** True when the session asks Soniox for a translation (interpret mode). */
    private readonly translating: boolean,
  ) {}

  handle(raw: string): void {
    let msg: { tokens?: SonioxToken[]; error_code?: number; error_message?: string };
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    if (msg.error_code != null || msg.error_message != null) {
      this.h.onError(msg.error_message ?? `Soniox error ${msg.error_code}`);
      return;
    }
    const tokens = Array.isArray(msg.tokens) ? msg.tokens : [];
    if (!tokens.length) return;
    let pendingOriginal = "";
    let pendingTranslation = "";
    for (const tok of tokens) {
      const text = typeof tok.text === "string" ? tok.text : "";
      if (MARKERS.has(text.trim())) {
        if (tok.is_final && text.trim() === "<end>") this.endpoint = true;
        continue;
      }
      if (!text) continue;
      const isTranslation = tok.translation_status === "translation";
      if (!tok.is_final) {
        if (isTranslation) pendingTranslation += text;
        else pendingOriginal += text;
        continue;
      }
      if (isTranslation) {
        this.translation += text;
      } else {
        this.open();
        this.original += text;
        if (typeof tok.start_ms === "number" && this.firstMs === null) this.firstMs = tok.start_ms;
        if (typeof tok.end_ms === "number") this.lastMs = tok.end_ms;
        if (tok.speaker) this.speakers[tok.speaker] = (this.speakers[tok.speaker] ?? 0) + text.length;
      }
    }
    this.pendingOriginal = pendingOriginal;
    this.pendingTranslation = pendingTranslation;
    if (pendingOriginal || pendingTranslation || this.translation) this.open();
    this.lastAt = this.now();
    this.emitInterim();
    const settled = !this.pendingOriginal && !this.pendingTranslation;
    if (this.endpoint && settled && (!this.translating || this.translation.trim() || !this.original.trim())) this.cut();
  }

  /** Safety net: close the sentence when nothing new arrived for ``idleMs``. */
  flushIdle(idleMs: number): void {
    if (this.itemId && this.now() - this.lastAt >= idleMs) {
      this.original += this.pendingOriginal;
      this.translation += this.pendingTranslation;
      this.pendingOriginal = this.pendingTranslation = "";
      this.cut();
    }
  }

  private open(): void {
    if (!this.itemId) this.itemId = `sx-${Math.round(this.baseMs)}-${++this.seq}`;
  }

  private emitInterim(): void {
    if (!this.itemId) return;
    const original = (this.original + this.pendingOriginal).trim();
    const translation = (this.translation + this.pendingTranslation).trim();
    this.h.onInterim(this.itemId, original, this.translating ? translation : undefined);
  }

  private cut(): void {
    const itemId = this.itemId;
    const text = this.original.trim();
    const translation = this.translation.trim();
    const speaker = Object.entries(this.speakers).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
    const startMs = Math.round(this.baseMs + (this.firstMs ?? Math.max(0, this.now() - this.baseMs - 1000)));
    const durationMs = this.firstMs !== null && this.lastMs !== null ? Math.max(0, this.lastMs - this.firstMs) : null;
    this.original = this.translation = "";
    this.speakers = {};
    this.firstMs = this.lastMs = null;
    this.endpoint = false;
    this.itemId = "";
    if (!itemId) return;
    this.h.onInterim(itemId, "", this.translating ? "" : undefined);
    if (text || translation) {
      this.h.onFinal({ itemId, text, translation: this.translating ? translation : undefined, startMs, durationMs, speaker });
    }
  }
}
