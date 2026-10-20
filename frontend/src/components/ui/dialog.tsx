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
      className={`m-auto w-[95vw] ${wide ? "max-w-3xl" : "max-w-lg"} rounded-[22px] border border-line bg-surface p-0 text-ink shadow-[var(--shadow)] backdrop:bg-[rgba(10,10,12,.7)] backdrop:backdrop-blur-sm`}
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <header className="flex items-center justify-between px-5 pt-4 pb-2">
            <h2 className="text-[15px] font-semibold">{title}</h2>
            <button type="button" onClick={onClose} className="rounded-full px-2 text-lg text-muted hover:bg-surface-2" aria-label={t.common.close}>
              ×
            </button>
          </header>
          <div className="overflow-y-auto px-5 py-3">{children}</div>
          {footer && <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
        </div>
      )}
    </dialog>
  );
}
