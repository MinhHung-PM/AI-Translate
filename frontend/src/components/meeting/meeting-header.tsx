"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Badge, cn } from "@/components/ui";
import { MeetingStatusBadge, MemoStatusBadge } from "@/components/shared/status";
import { formatDateTime } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useFeature } from "@/lib/session";
import type { Meeting } from "@/lib/types";

/** Meeting title block with the Transcript / Biên bản / Trực tiếp switch. */
export function MeetingHeader({ meeting, eyebrow }: { meeting: Meeting; eyebrow?: string }) {
  const pathname = usePathname();
  // Platform warnings only matter when a platform integration exists on this server.
  const platformWarning = useFeature("integrations") && meeting.platform_status !== "available";
  const replayDemo = useFeature("replay_demo");
  const base = `/meetings/${meeting.id}`;
  const tabs = [
    { href: base, label: t.workspace.tabs.transcript },
    { href: `${base}/memo`, label: t.workspace.tabs.memo },
    { href: `${base}/live`, label: replayDemo ? t.workspace.tabs.live : t.workspace.tabs.liveOnly },
  ];
  const src = meeting.source_language ?? meeting.detected_language;
  return (
    <div className="mb-4 flex flex-wrap items-end gap-3">
      <div className="flex min-w-60 flex-1 flex-col gap-1">
        <p className="eyebrow text-muted">
          <Link href={`/projects/${meeting.project_id}`} className="hover:text-ink">
            {meeting.project_name}
          </Link>
          {" · "}
          {eyebrow ?? t.meetingType[meeting.meeting_type]}
        </p>
        <h1 className="font-display text-[clamp(20px,2.4vw,26px)] leading-tight font-semibold">{meeting.title}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          <span>
            {formatDateTime(meeting.scheduled_at, meeting.timezone)} ({meeting.timezone})
          </span>
          <span aria-hidden>·</span>
          <span>
            {src ?? "auto"}
            {!meeting.source_language && meeting.detected_language && ` (${t.workspace.detected})`} ⇄ {meeting.target_language} · {t.meetingForm.memoLanguage.toLowerCase()}: {meeting.memo_language}
          </span>
          <MeetingStatusBadge status={meeting.status} />
          <MemoStatusBadge status={meeting.memo_status} />
          <Badge tone={platformWarning ? "warning" : "neutral"} title={platformWarning ? (meeting.platform_status === "not_linked" ? t.platform.notLinkedHint : t.platform.notConfiguredHint) : undefined}>
            {t.platform[meeting.platform]}
            {platformWarning && ` · ${meeting.platform_status === "not_linked" ? t.platform.not_linked : t.platform.not_configured}`}
          </Badge>
        </div>
      </div>
      <nav className="flex rounded-full border border-line p-0.5 text-[13px]" aria-label={t.workspace.sections}>
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={pathname === tab.href ? "page" : undefined}
            className={cn("rounded-full px-3.5 py-1.5 whitespace-nowrap", pathname === tab.href ? "bg-ink text-bg" : "text-muted hover:text-ink")}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
