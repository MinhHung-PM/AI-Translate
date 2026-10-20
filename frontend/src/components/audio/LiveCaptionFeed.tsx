"use client";

import { useEffect, useRef } from "react";
import { Fred, cn } from "@/components/ui";
import { formatMs, originalMissing } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { TranscriptEntry } from "@/lib/types";

export interface InterimCaption {
  sourceId: string;
  label: string;
  text: string;
  /** Live interpretation: translated words so far (shown as the headline). */
  translation?: string;
}

/** Caption display settings, controlled from the live status bar. */
export interface CaptionPrefs {
  /** Translation font size in px (16–34; the line being spoken is ~1.18×). */
  size: number;
  follow: boolean;
  onlyTranslation: boolean;
}

export const CAPTION_SIZE = { min: 16, max: 34, step: 2, initial: 22 } as const;

// Speaker colours: soft avatar + coloured name. The local user's microphones use the accent.
const PALETTE = [
  { name: "text-spk1", avatar: "bg-spk1-soft text-spk1" },
  { name: "text-spk3", avatar: "bg-spk3-soft text-spk3" },
  { name: "text-info", avatar: "bg-info-soft text-info" },
  { name: "text-danger", avatar: "bg-danger-soft text-danger" },
];
const SELF = { name: "text-accent-text", avatar: "bg-accent-soft text-accent-text" };

function colourFor(label: string | null, self: boolean) {
  if (self) return SELF;
  if (!label) return { name: "text-muted", avatar: "bg-surface-2 text-muted" };
  let h = 0;
  for (let i = 0; i < label.length; i++) h = (h * 31 + label.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

function initials(label: string | null): string {
  if (!label) return "?";
  const parts = label.trim().split(/\s+/);
  // "Người 2" → "N2", "Tanaka Ken" → "TK", "Tanaka" → "TA".
  if (parts.length > 1) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return label.trim().slice(0, 2).toUpperCase();
}

/**
 * Live captions as chat bubbles: the translation is the headline, the original line sits underneath
 * (smaller, muted), each speaker has a colour, and words still being spoken stream into a dashed
 * "đang nói…" bubble whose height is reserved so the feed doesn't jump as the line grows.
 */
export function LiveCaptionFeed({
  entries,
  interim,
  selfLabels,
  prefs = { size: CAPTION_SIZE.initial, follow: true, onlyTranslation: false },
}: {
  entries: TranscriptEntry[];
  interim: InterimCaption[];
  /** Speaker labels of the local user's microphones. */
  selfLabels: string[];
  prefs?: CaptionPrefs;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const interimText = interim.map((i) => i.text + (i.translation ?? "")).join("|");
  const fsSrc = Math.max(14, Math.round(prefs.size * 0.66));
  const fsLive = Math.round(prefs.size * 1.18);

  useEffect(() => {
    if (prefs.follow) endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [entries.length, interimText, prefs.follow]);

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-y-auto" data-testid="caption-feed" aria-label={t.captions.title}>
      <div className="mt-auto flex flex-col gap-4 px-[clamp(14px,2.4vw,32px)] pt-5 pb-7" aria-live="polite">
        {entries.length === 0 && interim.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-3 py-12 text-muted">
            <Fred pose="listening" className="h-32 w-auto animate-floaty" />
            <p className="font-medium">{t.captions.waiting}</p>
          </div>
        )}

        {entries.map((e) => {
          const label = e.speaker_label;
          const c = colourFor(label, !!label && selfLabels.includes(label));
          const tr = e.translation;
          return (
            <div key={e.id} className="flex max-w-[860px] animate-caption-in items-start gap-2.5" data-testid="caption-bubble">
              <span className={cn("flex size-[30px] shrink-0 items-center justify-center rounded-full text-[11px] font-bold", c.avatar)} title={label ?? t.captions.unknownSpeaker}>
                {initials(label)}
              </span>
              <div className="flex min-w-0 flex-col gap-1">
                <span className="text-xs text-muted">
                  <b className={cn("font-semibold", c.name)}>{label ?? t.captions.unknownSpeaker}</b>
                  {e.start_ms !== null && <> · {formatMs(e.start_ms)}</>}
                </span>
                <div className="flex flex-col gap-1.5 rounded-[4px_16px_16px_16px] border border-line bg-surface px-3.5 py-2.5">
                  {tr?.status === "done" && tr.text ? (
                    <p className="leading-[1.45]" style={{ fontSize: prefs.size }}>
                      {tr.text}
                    </p>
                  ) : tr?.status === "failed" ? (
                    <p className="text-sm text-danger">{t.captions.translateFailed}</p>
                  ) : (
                    <p className="leading-[1.45] text-subtle italic" style={{ fontSize: prefs.size }}>
                      {t.captions.translating}…
                    </p>
                  )}
                  {!prefs.onlyTranslation && (
                    <p className="leading-normal text-muted" style={{ fontSize: fsSrc }}>
                      {originalMissing(e) ? (
                        <span className="italic" data-testid="original-missing">{t.captions.noOriginal}</span>
                      ) : (
                        <>
                          {e.source_language && <span className="mr-1.5 rounded bg-surface-2 px-1 align-middle font-mono text-[10px] uppercase">{e.source_language}</span>}
                          {e.original_text}
                        </>
                      )}
                    </p>
                  )}
                  {tr?.ambiguity_note && <p className="text-xs text-warning">⚠ {tr.ambiguity_note}</p>}
                </div>
              </div>
            </div>
          );
        })}

        {interim.length > 0 && (
          <div className="flex flex-col gap-3" data-testid="interim-captions">
            {interim.map((i) => {
              const c = colourFor(i.label, selfLabels.includes(i.label));
              return (
                <div key={i.sourceId} className="flex max-w-[900px] items-start gap-2.5">
                  <span className={cn("flex size-[30px] shrink-0 items-center justify-center rounded-full text-[11px] font-bold", c.avatar)}>{initials(i.label)}</span>
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="text-xs font-semibold text-info">
                      {i.label} · {t.captions.speaking}…
                    </span>
                    <div
                      className="flex flex-col gap-1.5 rounded-[4px_16px_16px_16px] border-[1.5px] border-dashed border-info px-4 py-3"
                      style={{ minHeight: Math.round(fsLive * 1.4 * 2 + 24) }}
                    >
                      <p className="leading-[1.4] font-medium" style={{ fontSize: fsLive }}>
                        {i.translation || i.text}
                        <span className="animate-caret text-info" aria-hidden>
                          ▍
                        </span>
                      </p>
                      {i.translation && i.text && !prefs.onlyTranslation && (
                        <p className="text-muted" style={{ fontSize: fsSrc }} data-testid="interim-original">
                          {i.text}
                        </p>
                      )}
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
