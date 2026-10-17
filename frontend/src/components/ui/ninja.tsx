import { cn } from "./cn";

/** Original four-point shuriken mark (generic ninja motif, drawn for this app). */
export function Shuriken({ className, spin }: { className?: string; spin?: boolean }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden className={cn(spin && "animate-spin-slow", className)}>
      <path
        d="M32 2 L39 25 L62 32 L39 39 L32 62 L25 39 L2 32 L25 25 Z"
        fill="currentColor"
        stroke="#1b2440"
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <circle cx="32" cy="32" r="6" fill="#fdf6e9" stroke="#1b2440" strokeWidth="3" />
    </svg>
  );
}

/** Stylised swirl cloud (decorative). */
export function SwirlCloud({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 120 48" aria-hidden className={className}>
      <path
        d="M10 38c-6 0-8-8-2-11 0-9 11-12 16-6 4-9 18-9 22 0 5-6 15-3 15 5 7-2 12 6 7 11H10z"
        fill="currentColor"
        stroke="#1b2440"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path d="M36 30c3-4 9-1 6 3" fill="none" stroke="#1b2440" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}
