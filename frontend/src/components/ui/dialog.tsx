"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { t } from "@/lib/i18n";

/** Native <dialog>: focus trapping, Esc-to-close and inert background for free. */
export function Dialog({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-label={title}
      className={`m-auto w-[95vw] ${wide ? "max-w-3xl" : "max-w-lg"} rounded-lg border border-line p-0 shadow-xl backdrop:bg-black/30`}
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <header className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="text-sm font-semibold">{title}</h2>
            <button type="button" onClick={onClose} className="rounded px-2 text-muted hover:bg-gray-100" aria-label={t.common.close}>
              ×
            </button>
          </header>
          <div className="overflow-y-auto px-4 py-3">{children}</div>
          {footer && <footer className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</footer>}
        </div>
      )}
    </dialog>
  );
}
