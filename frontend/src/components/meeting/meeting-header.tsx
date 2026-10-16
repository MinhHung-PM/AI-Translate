"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Badge, cn } from "@/components/ui";
import { MeetingStatusBadge, MemoStatusBadge } from "@/components/shared/status";
import { formatDateTime } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { Meeting } from "@/lib/types";

export function MeetingHeader({ meeting }: { meeting: Meeting }) {
  const pathname = usePathname();
  const base = `/meetings/${meeting.id}`;
  const tabs = [
    { href: base, label: t.workspace.tabs.transcript },
    { href: `${base}/memo`, label: t.workspace.tabs.memo },
    { href: `${base}/live`, label: t.workspace.tabs.live },
  ];
  const src = meeting.source_language ?? meeting.detected_language;
  return (
    <div className="mb-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs text-muted">
            <Link href={`/projects/${meeting.project_id}`} className="hover:underline">
              {meeting.project_name}
            </Link>{" "}
            · {t.meetingType[meeting.meeting_type]}
          </p>
          <h1 className="text-lg font-semibold">{meeting.title}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>
              {formatDateTime(meeting.scheduled_at, meeting.timezone)} ({meeting.timezone})
            </span>
            <span>·</span>
            <span>
              {src ? t.languages[src] : t.languages.auto}
              {!meeting.source_language && meeting.detected_language && ` (${t.workspace.detected})`} → {t.languages[meeting.target_language]}
            </span>
            <span>·</span>
            <span>
              {t.meetingForm.memoLanguage}: {t.languages[meeting.memo_language]}
            </span>
            <MeetingStatusBadge status={meeting.status} />
            <MemoStatusBadge status={meeting.memo_status} />
            <Badge tone={meeting.platform_status === "available" ? "neutral" : "warning"} title={meeting.platform_status === "available" ? undefined : meeting.platform_status === "not_linked" ? t.platform.notLinkedHint : t.platform.notConfiguredHint}>
              {t.platform[meeting.platform]}
              {meeting.platform_status !== "available" && ` · ${meeting.platform_status === "not_linked" ? t.platform.not_linked : t.platform.not_configured}`}
            </Badge>
          </div>
        </div>
      </div>
      <nav className="mt-3 flex gap-1 border-b border-line" aria-label="Meeting sections">
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={pathname === tab.href ? "page" : undefined}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm",
              pathname === tab.href ? "border-brand-600 font-medium text-brand-700" : "border-transparent text-muted hover:text-ink",
            )}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
