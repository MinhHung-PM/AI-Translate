"use client";

import { useEffect, useRef, useState } from "react";
import { Shuriken, cn } from "@/components/ui";
import { formatMs } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { Language, TranscriptEntry } from "@/lib/types";

export interface InterimCaption {
  sourceId: string;
  label: string;
  text: string;
}

// Speaker colours: avatar ring + bubble tint (orange = "me").
const PALETTE = [
  { avatar: "bg-sky-500", bubble: "bg-sky-50" },
  { avatar: "bg-emerald-500", bubble: "bg-emerald-50" },
  { avatar: "bg-violet-500", bubble: "bg-violet-50" },
  { avatar: "bg-rose-500", bubble: "bg-rose-50" },
  { avatar: "bg-amber-500", bubble: "bg-amber-50" },
  { avatar: "bg-teal-600", bubble: "bg-teal-50" },
];

function colourFor(label: string) {
  let h = 0;
  for (let i = 0; i < label.length; i++) h = (h * 31 + label.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

function initials(label: string | null): string {
  if (!label) return "?";
  const parts = label.trim().split(/\s+/);
  // "Người 2" → "N2", "Tanaka Ken" → "TK", "Tôi" → "T".
  if (parts.length > 1) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return label.trim()[0].toUpperCase();
}

const SIZES = ["text-base", "text-lg", "text-xl", "text-2xl"] as const;

/**
 * Live captions as manga speech bubbles: the translation is the headline,
 * the original line sits underneath, each speaker has an avatar colour, and
 * words still being spoken appear in a "typing" bubble at the end.
 */
export function LiveCaptionFeed({
  entries,
  target,
  interim,
  selfLabels,
}: {
  entries: TranscriptEntry[];
  target: Language;
  interim: InterimCaption[];
  /** Speaker labels shown on the right side (the local user's microphones). */
  selfLabels: string[];
}) {
  const [size, setSize] = useState(1);
  const [follow, setFollow] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);
  const interimText = interim.map((i) => i.text).join("|");

  useEffect(() => {
    if (follow) endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [entries.length, interimText, follow]);

  return (
    <section className="panel overflow-hidden" data-testid="caption-feed">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b-2 border-ink bg-navy-800 px-4 py-2 text-white">
        <h2 className="flex items-center gap-2 text-sm font-black tracking-wide">
          <Shuriken className="size-5 text-brand-500" spin={interim.length > 0} />
          {t.captions.title}
          <span className="rounded-full bg-white/15 px-2 py-0.5 text-[11px] font-bold">
            {t.languages[target]}
          </span>
        </h2>
        <div className="flex items-center gap-1.5 text-xs">
          <span className="mr-1 text-white/70">{t.captions.textSize}</span>
          <button
            type="button"
            className="rounded-md border-2 border-white/40 px-2 font-black hover:bg-white/10 disabled:opacity-40"
            onClick={() => setSize((s) => Math.max(0, s - 1))}
            disabled={size === 0}
            aria-label={t.captions.smaller}
          >
            A−
          </button>
          <button
            type="button"
            className="rounded-md border-2 border-white/40 px-2 font-black hover:bg-white/10 disabled:opacity-40"
            onClick={() => setSize((s) => Math.min(SIZES.length - 1, s + 1))}
            disabled={size === SIZES.length - 1}
            aria-label={t.captions.larger}
          >
            A+
          </button>
          <label className="ml-2 inline-flex items-center gap-1 text-white/80">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
            {t.captions.follow}
          </label>
        </div>
      </header>

      <div className="max-h-[65vh] min-h-64 space-y-4 overflow-y-auto bg-[radial-gradient(rgb(27_36_64/0.06)_1px,transparent_1.2px)] [background-size:12px_12px] p-4">
        {entries.length === 0 && interim.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted">
            <Shuriken className="size-10 text-brand-500/70" spin />
            <p className="font-semibold">{t.captions.waiting}</p>
          </div>
        )}

        {entries.map((e) => {
          const label = e.speaker_label;
          const self = !!label && selfLabels.includes(label);
          const c = label ? colourFor(label) : null;
          const tr = e.translation;
          return (
            <div key={e.id} className={cn("flex animate-caption-in items-end gap-2.5", self && "flex-row-reverse")} data-testid="caption-bubble">
              <div
                className={cn(
                  "flex size-10 shrink-0 items-center justify-center rounded-full border-2 border-ink text-xs font-black text-white shadow-[var(--shadow-panel-sm)]",
                  self ? "bg-brand-500" : (c?.avatar ?? "bg-gray-400"),
                )}
                title={label ?? t.captions.unknownSpeaker}
              >
                {initials(label)}
              </div>
              <div className={cn("max-w-[80%] min-w-0", self && "text-right")}>
                <p className={cn("mb-1 text-xs font-bold text-muted", self && "text-right")}>
                  {label ?? t.captions.unknownSpeaker}
                  {e.start_ms !== null && <span className="ml-2 font-normal">{formatMs(e.start_ms)}</span>}
                </p>
                <div
                  className={cn(
                    "relative rounded-2xl border-2 border-ink px-4 py-2.5 text-left shadow-[var(--shadow-panel-sm)]",
                    self ? "rounded-br-sm bg-brand-50" : cn("rounded-bl-sm", c?.bubble ?? "bg-white"),
                  )}
                >
                  {tr?.status === "done" && tr.text ? (
                    <p className={cn("leading-snug font-bold text-ink", SIZES[size])}>{tr.text}</p>
                  ) : tr?.status === "failed" ? (
                    <p className="text-sm font-semibold text-red-700">{t.captions.translateFailed}</p>
                  ) : (
                    <p className={cn("leading-snug font-bold text-ink/50 italic", SIZES[size])}>
                      {t.captions.translating}
                      <Dots />
                    </p>
                  )}
                  <p className="mt-1.5 border-t border-dashed border-ink/20 pt-1.5 text-sm text-muted">
                    {e.source_language && (
                      <span className="mr-1.5 rounded bg-ink/10 px-1 text-[10px] font-bold uppercase text-ink/70">{e.source_language}</span>
                    )}
                    {e.original_text}
                  </p>
                  {tr?.ambiguity_note && <p className="mt-1 text-xs text-amber-800">⚠ {tr.ambiguity_note}</p>}
                </div>
              </div>
            </div>
          );
        })}

        {interim.length > 0 && (
          <div className="space-y-2" data-testid="interim-captions" aria-live="polite">
            {interim.map((i) => {
              const self = selfLabels.includes(i.label);
              return (
                <div key={i.sourceId} className={cn("flex items-end gap-2.5", self && "flex-row-reverse")}>
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-full border-2 border-dashed border-ink bg-white text-xs font-black text-ink">
                    {initials(i.label)}
                  </div>
                  <div className={cn("max-w-[80%]", self && "text-right")}>
                    <p className="mb-1 text-xs font-bold text-brand-700">
                      {i.label} · {t.captions.speaking}
                    </p>
                    <div className="rounded-2xl border-2 border-dashed border-ink bg-white px-4 py-2.5 text-left">
                      <p className={cn("leading-snug text-ink", SIZES[size])}>
                        {i.text}
                        <Dots />
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <div ref={endRef} />
      </div>
    </section>
  );
}

function Dots() {
  return (
    <span className="ml-1 inline-flex gap-0.5 align-middle" aria-hidden>
      {[0, 1, 2].map((i) => (
        <span key={i} className="typing-dot inline-block size-1.5 rounded-full bg-brand-500" style={{ animationDelay: `${i * 0.15}s` }} />
      ))}
    </span>
  );
}
