import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "inverse";
type Size = "sm" | "md" | "lg";

// Pill buttons: mustard primary, hairline secondary, ink-on-text "inverse" for the strong neutral action.
const variants: Record<Variant, string> = {
  primary: "bg-accent font-bold text-accent-ink hover:brightness-105 disabled:bg-surface-2 disabled:text-subtle",
  secondary: "border border-line-strong bg-transparent text-ink hover:bg-surface-2 disabled:text-subtle",
  ghost: "text-ink hover:bg-surface-2 disabled:text-subtle",
  danger: "border border-danger-line bg-transparent text-danger hover:bg-danger-soft disabled:opacity-50",
  inverse: "bg-ink font-semibold text-bg hover:opacity-90 disabled:opacity-50",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-10 px-4 text-sm",
  lg: "h-13 px-7 font-display text-[15px] font-semibold",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, className, disabled, children, type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-full font-medium whitespace-nowrap transition-[background-color,opacity,filter] disabled:cursor-not-allowed",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {loading && <span className="size-3 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />}
      {children}
    </button>
  );
});
