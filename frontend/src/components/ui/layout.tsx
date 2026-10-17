import type { ReactNode } from "react";
import { cn } from "./cn";

export function Card({ title, actions, children, className, bodyClassName }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string }) {
  return (
    <section className={cn("panel overflow-hidden", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b-2 border-ink bg-brand-50 px-4 py-2.5">
          {title && (
            <h2 className="flex items-center gap-2 text-sm font-extrabold tracking-tight text-ink">
              <span aria-hidden className="inline-block size-2.5 rotate-45 rounded-[2px] bg-brand-500 ring-2 ring-ink" />
              {title}
            </h2>
          )}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="relative inline-block text-2xl font-black tracking-tight text-ink">
          <span aria-hidden className="speed-lines absolute -inset-x-2 bottom-0.5 h-3 -skew-x-12 rounded-sm" />
          <span className="relative">{title}</span>
        </h1>
        {subtitle && <div className="mt-0.5 text-sm text-muted">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-sm [&_td]:border-b [&_td]:border-line [&_td]:px-3 [&_td]:py-2 [&_td]:align-top [&_th]:border-b-2 [&_th]:border-ink [&_th]:bg-scroll [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:text-xs [&_th]:font-medium [&_th]:text-muted">
        {children}
      </table>
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "danger" | "warning" }) {
  return (
    <div className="panel px-4 py-3 transition-transform hover:-translate-y-0.5">
      <p className="text-xs font-semibold text-muted">{label}</p>
      <p className={cn("mt-1 text-2xl font-black tabular-nums text-ink", tone === "danger" && "text-red-700", tone === "warning" && "text-amber-700")}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { value: T; label: ReactNode }[] }) {
  return (
    <div role="tablist" className="mb-4 inline-flex flex-wrap gap-1.5 rounded-full border-2 border-ink bg-white p-1 shadow-[var(--shadow-panel-sm)]">
      {items.map((item) => (
        <button
          key={item.value}
          role="tab"
          type="button"
          aria-selected={item.value === value}
          onClick={() => onChange(item.value)}
          className={cn(
            "rounded-full px-4 py-1.5 text-sm font-bold transition-colors",
            item.value === value ? "bg-brand-500 text-white" : "text-muted hover:bg-brand-50 hover:text-ink",
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
