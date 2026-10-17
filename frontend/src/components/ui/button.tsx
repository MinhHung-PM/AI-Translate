import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

// Comic buttons: ink outline + offset shadow that "presses" on click.
const pop =
  "border-2 border-ink shadow-[var(--shadow-panel-sm)] hover:-translate-y-px active:translate-x-[2px] active:translate-y-[2px] active:shadow-none disabled:translate-none disabled:shadow-none";
const variants: Record<Variant, string> = {
  primary: `${pop} bg-brand-500 text-white hover:bg-brand-600 disabled:bg-brand-500/50`,
  secondary: `${pop} bg-white text-ink hover:bg-brand-50 disabled:text-muted`,
  ghost: "text-ink hover:bg-brand-50 disabled:text-muted",
  danger: `${pop} bg-white text-red-700 hover:bg-red-50 disabled:text-red-300`,
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-10 px-4 text-sm",
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
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-bold whitespace-nowrap transition-[transform,background-color,box-shadow] disabled:cursor-not-allowed",
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
