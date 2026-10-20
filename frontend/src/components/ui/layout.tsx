import type { ReactNode } from "react";
import { cn } from "./cn";

export function Card({ title, actions, children, className, bodyClassName }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string }) {
  return (
    <section className={cn("panel overflow-hidden", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4 pb-1">
          {title && <h2 className="text-[15px] font-semibold text-ink">{title}</h2>}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("p-5", (title || actions) && "pt-3", bodyClassName)}>{children}</div>
    </section>
  );
}

/** Page title: mono eyebrow + Unbounded display heading. */
export function PageHeader({ title, eyebrow, subtitle, actions }: { title: ReactNode; eyebrow?: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="flex min-w-60 flex-1 flex-col gap-1">
        {eyebrow && <span className="eyebrow text-muted">{eyebrow}</span>}
        <h1 className="font-display text-[clamp(20px,2.4vw,26px)] leading-tight font-semibold text-ink">{title}</h1>
        {subtitle && <div className="text-sm text-muted">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-sm [&_td]:border-b [&_td]:border-line [&_td]:px-4 [&_td]:py-3 [&_td]:align-top [&_th]:border-b [&_th]:border-line [&_th]:bg-surface-2 [&_th]:px-4 [&_th]:py-2.5 [&_th]:text-left [&_th]:font-mono [&_th]:text-[10.5px] [&_th]:font-medium [&_th]:tracking-wider [&_th]:text-muted [&_th]:uppercase [&_tr:last-child_td]:border-b-0">
        {children}
      </table>
    </div>
  );
}

const statTones = { muted: "text-muted", warning: "text-warning", danger: "text-danger", info: "text-info" } as const;

/** Metric tile: mono label tinted by meaning, big Unbounded number. */
export function Stat({ label, value, hint, tone = "muted" }: { label: string; value: ReactNode; hint?: ReactNode; tone?: keyof typeof statTones }) {
  return (
    <div className="flex h-full flex-col gap-1.5 rounded-[14px] border border-line bg-surface p-4">
      <p className={cn("eyebrow", statTones[tone])}>{label}</p>
      <p className="font-display text-[28px] leading-none font-semibold text-ink tabular-nums">{value}</p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

/** Segmented pill tabs (selected = inverted ink). */
export function Tabs<T extends string>({ value, onChange, items, className, size = "md" }: { value: T; onChange: (v: T) => void; items: { value: T; label: ReactNode }[]; className?: string; size?: "sm" | "md" }) {
  return (
    <div role="tablist" className={cn("inline-flex flex-wrap rounded-full border border-line p-0.5", size === "sm" ? "text-xs" : "text-[13px]", className)}>
      {items.map((item) => (
        <button
          key={item.value}
          role="tab"
          type="button"
          aria-selected={item.value === value}
          onClick={() => onChange(item.value)}
          className={cn(
            "rounded-full whitespace-nowrap transition-colors",
            size === "sm" ? "px-3 py-1" : "px-3.5 py-1.5",
            item.value === value ? "bg-ink text-bg" : "text-muted hover:text-ink",
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

/** Toggle chip used for filters and radio-like option groups. */
export function Chip({ on, onClick, children, tone, role, className, disabled, ...rest }: { on: boolean; onClick: () => void; children: ReactNode; tone?: "warning" | "danger"; role?: "radio" | "switch"; className?: string; disabled?: boolean; "data-testid"?: string }) {
  return (
    <button
      type="button"
      role={role}
      aria-checked={role ? on : undefined}
      aria-pressed={role ? undefined : on}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-full border px-3 py-1.5 text-[13px] whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        on ? "border-ink bg-ink text-bg" : cn("border-line-strong bg-transparent hover:bg-surface-2", tone === "warning" ? "text-warning" : tone === "danger" ? "text-danger" : "text-ink"),
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
