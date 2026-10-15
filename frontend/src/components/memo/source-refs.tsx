import Link from "next/link";
import { formatMs } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { SourceRef } from "@/lib/types";

/** Links an extracted item back to the transcript lines it came from. */
export function SourceRefs({ meetingId, sources }: { meetingId: string; sources: SourceRef[] }) {
  if (sources.length === 0) return <span className="text-xs text-muted">{t.common.source}: {t.common.none}</span>;
  return (
    <div className="mt-1 space-y-1">
      {sources.map((s) => (
        <div key={s.entry_id} className="text-xs">
          <Link href={`/meetings/${meetingId}?entry=${s.entry_id}`} className="font-mono text-brand-700 hover:underline" title={t.common.openSource}>
            #{s.sequence}
            {s.start_ms !== null && ` ${formatMs(s.start_ms)}`}
            {s.speaker_label && ` · ${s.speaker_label}`}
          </Link>
          {s.excerpt && <span className="ml-1 text-muted">“{s.excerpt.length > 140 ? `${s.excerpt.slice(0, 140)}…` : s.excerpt}”</span>}
        </div>
      ))}
    </div>
  );
}

export function EntryIdRefs({ meetingId, ids }: { meetingId: string; ids: string[] }) {
  if (!ids.length) return null;
  return (
    <span className="ml-1 text-xs">
      {ids.map((eid, i) => (
        <Link key={eid} href={`/meetings/${meetingId}?entry=${eid}`} className="text-brand-700 hover:underline" title={t.common.openSource}>
          [{i + 1}]
        </Link>
      ))}
    </span>
  );
}
