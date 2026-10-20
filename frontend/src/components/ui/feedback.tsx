import type { ReactNode } from "react";
import { cn } from "./cn";
import { Fred, type FredPose } from "./fred";

type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "brand";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted",
  info: "bg-info-soft text-info",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  brand: "bg-accent-soft text-accent-text",
};

/** Small mono tag (status, MOCK / DEMO labels, "AI ĐỀ XUẤT"). */
export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10.5px] font-medium tracking-wide whitespace-nowrap", tones[tone], className)}>
      {children}
    </span>
  );
}

const alertTones: Record<Tone, string> = {
  neutral: "border-line bg-surface text-ink",
  info: "border-transparent bg-info-soft text-ink [&_b]:text-info",
  success: "border-transparent bg-success-soft text-ink",
  warning: "border-transparent bg-warning-soft text-ink",
  danger: "border-danger-line bg-danger-soft text-ink",
  brand: "border-accent bg-accent-soft text-ink",
};

const alertMark: Record<Tone, string> = { neutral: "text-muted", info: "text-info", success: "text-success", warning: "text-warning", danger: "text-danger", brand: "text-accent-text" };

export function Alert({ tone = "info", title, children, className, fred }: { tone?: Tone; title?: string; children?: ReactNode; className?: string; fred?: FredPose }) {
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex items-start gap-3 rounded-xl border px-3.5 py-2.5 text-sm leading-normal", alertTones[tone], className)}>
      {fred ? (
        <Fred pose={fred} className="-my-1 h-10 w-auto shrink-0" />
      ) : (
        <span aria-hidden className={cn("font-bold", alertMark[tone])}>
          {tone === "danger" ? "!" : tone === "success" ? "✓" : tone === "warning" ? "⚠" : "i"}
        </span>
      )}
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cn(title && "mt-0.5")}>{children}</div>}
      </div>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted" role="status">
      <span className="size-4 animate-spin rounded-full border-2 border-accent border-t-transparent" aria-hidden />
      {label}
    </div>
  );
}

/** Empty / no-result state; Fred points the way when a pose is given. */
export function EmptyState({ title, hint, action, fred }: { title: string; hint?: ReactNode; action?: ReactNode; fred?: FredPose }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-5 rounded-2xl border border-dashed border-line-strong px-5 py-8 text-sm">
      {fred && <Fred pose={fred} className="h-24 w-auto" />}
      <div className="flex flex-col items-start gap-2">
        <p className="font-medium text-ink">{title}</p>
        {hint && <p className="text-muted">{hint}</p>}
        {action}
      </div>
    </div>
  );
}

export function ProgressBar({ value, max, label, tone = "success" }: { value: number; max: number; label?: string; tone?: "success" | "accent" }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2" aria-label={label}>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn("h-full transition-all", tone === "accent" ? "bg-accent" : "bg-success")} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-20 shrink-0 text-right text-xs text-muted tabular-nums">
        {value}/{max}
      </span>
    </div>
  );
}
