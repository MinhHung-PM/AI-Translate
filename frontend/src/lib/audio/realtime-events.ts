/**
 * Pure handler for OpenAI Realtime transcription events (data channel
 * "oai-events"). Event names/fields follow openai/openai-openapi:
 *   input_audio_buffer.speech_started  {item_id, audio_start_ms}
 *   input_audio_buffer.speech_stopped  {item_id, audio_end_ms}
 *   conversation.item.input_audio_transcription.delta     {item_id, delta}
 *   conversation.item.input_audio_transcription.segment   {item_id, speaker, text}
 *   conversation.item.input_audio_transcription.completed {item_id, transcript}
 *   conversation.item.input_audio_transcription.failed    {item_id, error}
 *   error {error: {message}}
 */
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
      it = { text: "", startMs: null, endMs: null, speakers: {} };
      this.items.set(id, it);
    }
    return it;
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
        if (!id || typeof ev.delta !== "string") return;
        const it = this.item(id);
        if (it.startMs === null) it.startMs = this.now();
        it.text += ev.delta;
        this.h.onInterim(id, it.text);
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
        const it = this.item(id);
        this.items.delete(id);
        const text = (typeof ev.transcript === "string" ? ev.transcript : it.text).trim();
        this.h.onInterim(id, "");
        if (!text) return;
        const start = it.startMs ?? this.now();
        const speakers = Object.entries(it.speakers).sort((a, b) => b[1] - a[1]);
        this.h.onFinal({
          itemId: id,
          text,
          startMs: Math.max(0, Math.round(start)),
          durationMs: it.endMs !== null ? Math.max(0, Math.round(it.endMs - start)) : null,
          speaker: speakers[0]?.[0] ?? null,
        });
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
        const err = ev.error as { message?: string } | undefined;
        this.h.onError(err?.message ?? "Realtime error");
        return;
      }
      default:
        return;
    }
  }
}
