import Link from "next/link";
import { formatMs } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { SourceRef } from "@/lib/types";

/** "Nguồn #12 00:31 · Tanaka ↗" — opens the transcript at that line. */
export function SourceLink({ meetingId, source }: { meetingId: string; source: SourceRef }) {
  return (
    <Link href={`/meetings/${meetingId}?entry=${source.entry_id}`} className="text-info hover:underline" title={t.common.openSource}>
      {t.common.source} <span className="font-mono">#{source.sequence}</span>
      {source.start_ms !== null && ` ${formatMs(source.start_ms)}`}
      {source.speaker_label && ` · ${source.speaker_label}`} ↗
    </Link>
  );
}

/** The transcript lines an extracted item came from, quoted. */
export function SourceRefs({ meetingId, sources }: { meetingId: string; sources: SourceRef[] }) {
  if (sources.length === 0) return <span className="text-xs text-muted">{t.common.source}: {t.common.none}</span>;
  return (
    <div className="flex flex-col gap-1.5">
      {sources.map((s) => (
        <div key={s.entry_id} className="rounded-r-lg border-l-2 border-accent bg-accent-soft px-3 py-2 text-[13px] leading-normal">
          <Link href={`/meetings/${meetingId}?entry=${s.entry_id}`} className="font-mono text-[11px] text-muted hover:underline" title={t.common.openSource}>
            #{s.sequence}
            {s.start_ms !== null && ` · ${formatMs(s.start_ms)}`}
            {s.speaker_label && ` · ${s.speaker_label}`}
          </Link>
          {s.excerpt && <p>{s.excerpt}</p>}
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
        <Link key={eid} href={`/meetings/${meetingId}?entry=${eid}`} className="text-info hover:underline" title={t.common.openSource}>
          [{i + 1}]
        </Link>
      ))}
    </span>
  );
}
