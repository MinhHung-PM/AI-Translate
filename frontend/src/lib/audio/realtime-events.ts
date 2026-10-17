/**
 * Pure handler for OpenAI Realtime transcription events (data channel
 * "oai-events"). Event names/fields follow openai/openai-openapi:
 *   input_audio_buffer.speech_started  {item_id, audio_start_ms}
 *   input_audio_buffer.speech_stopped  {item_id, audio_end_ms}
 *   conversation.item.input_audio_transcription.delta     {item_id, delta}
 *   conversation.item.input_audio_transcription.segment   {item_id, speaker, text}
 *   conversation.item.input_audio_transcription.completed {item_id, transcript}
 *   conversation.item.input_audio_transcription.failed    {item_id, error}
 *   input_audio_buffer.committed {item_id}   (after the browser's input_audio_buffer.commit)
 *   error {error: {message}}
 * Streaming models without server VAD (gpt-realtime-whisper) may send deltas
 * before an item exists; they are kept under a provisional key and attached to
 * the item announced by the next "committed" event.
 */
const LIVE = "__live";
export interface FinalUtterance {
  itemId: string;
  text: string;
  /** Offset from the capture start (shared clock across sources), ms. */
  startMs: number;
  durationMs: number | null;
  speaker: string | null;
}

export interface RealtimeHandlers {
  onInterim: (itemId: string, text: string) => void;
  onFinal: (u: FinalUtterance) => void;
  onError: (message: string) => void;
}

interface ItemState {
  text: string;
  startMs: number | null;
  endMs: number | null;
  speakers: Record<string, number>;
  updatedAt: number;
}

export class RealtimeEventProcessor {
  private items = new Map<string, ItemState>();
  /** Capture-clock time (ms) at which this connection's audio started. */
  baseMs = 0;
  /** Capture-clock "now", used when the provider sends no timestamps. */
  now: () => number = () => this.baseMs;

  constructor(private readonly h: RealtimeHandlers) {}

  private item(id: string): ItemState {
    let it = this.items.get(id);
    if (!it) {
      it = { text: "", startMs: null, endMs: null, speakers: {}, updatedAt: this.now() };
      this.items.set(id, it);
    }
    return it;
  }

  private localSeq = 0;

  /** Text currently shown as "being spoken" (any item). */
  hasPending(): boolean {
    for (const it of this.items.values()) if (it.text.trim()) return true;
    return false;
  }

  /**
   * Safety net: finalize items whose text stopped changing ``idleMs`` ago but
   * never received a "completed" event (so no spoken text is lost).
   */
  flushStale(idleMs: number): void {
    const now = this.now();
    for (const [id, it] of [...this.items.entries()]) {
      if (it.text.trim() && now - it.updatedAt >= idleMs) this.finalize(id === LIVE ? `local-${++this.localSeq}-${Math.round(now)}` : id, id, it.text);
    }
  }

  private finalize(finalId: string, key: string, transcript: string): void {
    const it = this.item(key);
    this.items.delete(key);
    const text = transcript.trim();
    this.h.onInterim(key, "");
    if (key !== finalId) this.h.onInterim(finalId, "");
    if (!text) return;
    const start = it.startMs ?? this.now();
    const speakers = Object.entries(it.speakers).sort((a, b) => b[1] - a[1]);
    this.h.onFinal({
      itemId: finalId,
      text,
      startMs: Math.max(0, Math.round(start)),
      durationMs: it.endMs !== null ? Math.max(0, Math.round(it.endMs - start)) : null,
      speaker: speakers[0]?.[0] ?? null,
    });
  }

  handle(raw: string): void {
    let ev: Record<string, unknown>;
    try {
      ev = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    const type = String(ev.type ?? "");
    const id = typeof ev.item_id === "string" ? ev.item_id : "";
    if (type === "input_audio_buffer.committed") {
      // Attach provisional streamed text to the item that now exists.
      const live = this.items.get(LIVE);
      if (id && live) {
        this.items.delete(LIVE);
        const existing = this.items.get(id);
        if (existing) existing.text = live.text + existing.text;
        else this.items.set(id, live);
        this.h.onInterim(LIVE, "");
        this.h.onInterim(id, (existing ?? live).text);
      }
      return;
    }
    switch (type) {
      case "input_audio_buffer.speech_started": {
        if (!id) return;
        const it = this.item(id);
        it.startMs = typeof ev.audio_start_ms === "number" ? this.baseMs + ev.audio_start_ms : this.now();
        return;
      }
      case "input_audio_buffer.speech_stopped": {
        if (!id) return;
        const it = this.item(id);
        it.endMs = typeof ev.audio_end_ms === "number" ? this.baseMs + ev.audio_end_ms : this.now();
        return;
      }
      case "conversation.item.input_audio_transcription.delta": {
        if (typeof ev.delta !== "string") return;
        const key = id || LIVE;
        const it = this.item(key);
        if (it.startMs === null) it.startMs = this.now();
        it.text += ev.delta;
        it.updatedAt = this.now();
        this.h.onInterim(key, it.text);
        return;
      }
      case "conversation.item.input_audio_transcription.segment": {
        if (!id || typeof ev.speaker !== "string") return;
        const it = this.item(id);
        const len = typeof ev.text === "string" ? ev.text.length : 1;
        it.speakers[ev.speaker] = (it.speakers[ev.speaker] ?? 0) + len;
        return;
      }
      case "conversation.item.input_audio_transcription.completed": {
        if (!id) return;
        const key = this.items.has(id) || !this.items.has(LIVE) ? id : LIVE;
        const it = this.item(key);
        this.finalize(id, key, typeof ev.transcript === "string" ? ev.transcript : it.text);
        return;
      }
      case "conversation.item.input_audio_transcription.failed": {
        if (id) {
          this.items.delete(id);
          this.h.onInterim(id, "");
        }
        const err = ev.error as { message?: string } | undefined;
        this.h.onError(err?.message ?? "Transcription failed for one utterance");
        return;
      }
      case "error": {
        const err = ev.error as { message?: string; code?: string } | undefined;
        // Committing while nothing new was heard is harmless.
        if (err?.code === "input_audio_buffer_commit_empty") return;
        this.h.onError(err?.message ?? "Realtime error");
        return;
      }
      default:
        return;
    }
  }
}
