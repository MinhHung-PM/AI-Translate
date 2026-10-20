import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "./cn";

const control =
  "w-full rounded-[10px] border border-line-strong bg-bg px-3 py-2 text-sm text-ink placeholder:text-subtle focus:border-info focus:outline-none disabled:bg-surface-2 disabled:text-muted";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={cn(control, "h-10", className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...props },
  ref,
) {
  return <textarea ref={ref} className={cn(control, "min-h-20 leading-normal", className)} {...props} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...props },
  ref,
) {
  return (
    <select ref={ref} className={cn(control, "h-10 bg-surface pr-8", className)} {...props}>
      {children}
    </select>
  );
});

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  children: (id: string) => ReactNode;
  className?: string;
}

/** Label + control + hint/error, wired with ids for screen readers. */
export function Field({ label, hint, error, children, className }: FieldProps) {
  const id = useId();
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-xs text-muted">
        {label}
      </label>
      {children(id)}
      {hint && !error && <p className="text-xs text-muted">{hint}</p>}
      {error && (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function Checkbox({ label, className, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label className={cn("inline-flex cursor-pointer items-center gap-2.5 text-sm", props.disabled && "cursor-not-allowed text-muted", className)}>
      <input type="checkbox" className="size-4 shrink-0 accent-accent" {...props} />
      {label}
    </label>
  );
}

/** Compact labelled filter ("Dự án  Tất cả ▾"): wrap a Select/Input and pass it `pillControl`. */
export function FilterPill({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("flex h-9 items-center gap-1.5 rounded-[10px] border border-line bg-surface pl-3 text-[13px] focus-within:border-info", className)}>
      <span className="whitespace-nowrap text-muted">{label}</span>
      {children}
    </label>
  );
}

export const pillControl = "h-8 w-auto min-w-0 border-0 bg-transparent py-0 pl-1 text-[13px] focus:border-0";
