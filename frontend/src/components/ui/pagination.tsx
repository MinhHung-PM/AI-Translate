import { t } from "@/lib/i18n";
import { Button } from "./button";

export function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return (
    <nav className="mt-3 flex items-center justify-end gap-2 text-sm" aria-label="pagination">
      <Button size="sm" onClick={() => onChange(page - 1)} disabled={page <= 1}>
        {t.common.prev}
      </Button>
      <span className="text-muted tabular-nums">
        {t.common.page} {page} {t.common.of} {pages} · {total}
      </span>
      <Button size="sm" onClick={() => onChange(page + 1)} disabled={page >= pages}>
        {t.common.next}
      </Button>
    </nav>
  );
}
