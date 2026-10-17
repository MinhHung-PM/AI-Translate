import type { ReactNode } from "react";
import { cn } from "./cn";

type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "brand";

const tones: Record<Tone, string> = {
  neutral: "bg-gray-100 text-gray-700 ring-gray-200",
  info: "bg-sky-50 text-sky-800 ring-sky-200",
  success: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  warning: "bg-amber-50 text-amber-800 ring-amber-200",
  danger: "bg-red-50 text-red-700 ring-red-200",
  brand: "bg-brand-100 text-brand-700 ring-brand-500/40",
};

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold whitespace-nowrap ring-1 ring-inset", tones[tone], className)}>
      {children}
    </span>
  );
}

export function Alert({ tone = "info", title, children, className }: { tone?: Tone; title?: string; children?: ReactNode; className?: string }) {
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("rounded-lg border-l-4 border-current/40 px-3 py-2 text-sm ring-1 ring-inset", tones[tone], className)}>
      {title && <p className="font-medium">{title}</p>}
      {children && <div className={cn(title && "mt-0.5")}>{children}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted" role="status">
      <span className="size-4 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" aria-hidden />
      {label}
    </div>
  );
}

export function EmptyState({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-md border border-dashed border-line px-4 py-10 text-center text-sm text-muted">
      <p>{title}</p>
      {action}
    </div>
  );
}

export function ProgressBar({ value, max, label }: { value: number; max: number; label?: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2" aria-label={label}>
      <div className="h-1.5 w-full overflow-hidden rounded bg-gray-200" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-brand-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-20 shrink-0 text-right text-xs text-muted tabular-nums">
        {value}/{max}
      </span>
    </div>
  );
}
