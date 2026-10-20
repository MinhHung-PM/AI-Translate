"use client";

import Image from "next/image";
import { usePrefs } from "@/lib/prefs";
import { cn } from "./cn";

// Intrinsic sizes of the transparent cut-outs in /public/fred.
const POSES = {
  wave: [632, 464],
  crossed: [528, 479],
  pointing: [724, 456],
  listening: [667, 462],
  headphones: [711, 476],
  clipboard: [592, 478],
  thinking: [517, 459],
  happy: [714, 482],
  sad: [551, 459],
} as const;

export type FredPose = keyof typeof POSES;

/**
 * Fred, the astronaut mascot. One pose per context: wave (home), crossed / pointing (live setup),
 * headphones (listening), clipboard (minutes), thinking (AI working, ambiguity), happy / sad (success, error).
 * Renders nothing when the user has hidden Fred.
 */
export function Fred({ pose, alt = "", className, priority }: { pose: FredPose; alt?: string; className?: string; priority?: boolean }) {
  const { showFred } = usePrefs();
  if (!showFred) return null;
  const [width, height] = POSES[pose];
  return <Image src={`/fred/${pose}.webp`} alt={alt} width={width} height={height} unoptimized priority={priority} className={cn("h-auto select-none", className)} draggable={false} />;
}

/** Fred's speech bubble (ink-on-cream in dark mode, inverted in light). */
export function FredSays({ children, className }: { children: React.ReactNode; className?: string }) {
  const { showFred } = usePrefs();
  if (!showFred) return null;
  return <div className={cn("rounded-[18px_18px_18px_4px] bg-bubble px-4 py-3 text-sm leading-normal font-medium text-bubble-ink", className)}>{children}</div>;
}
