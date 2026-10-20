import type { ReactNode } from "react";
import { Badge, cn } from "@/components/ui";
import { t } from "@/lib/i18n";
import type { ActionStatus, MeetingStatus, MemoStatus, Priority, TranslationStatus, VerificationStatus } from "@/lib/types";

type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "brand";

const pillTones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted",
  info: "bg-info-soft text-info",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  brand: "bg-accent-soft text-accent-text",
};

/** Rounded status pill ("Chờ duyệt", "Đã duyệt"…). */
export function StatusPill({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs whitespace-nowrap", pillTones[tone])}>
      {children}
    </span>
  );
}

export function MemoStatusBadge({ status }: { status: MemoStatus | null }) {
  if (!status) return <StatusPill tone="neutral">{t.memoStatus.none}</StatusPill>;
  const tone = { generating: "info", failed: "danger", draft: "neutral", in_review: "warning", approved: "success", rejected: "danger" } as const;
  return <StatusPill tone={tone[status]}>{t.memoStatus[status]}</StatusPill>;
}

export function MeetingStatusBadge({ status }: { status: MeetingStatus }) {
  const tone = { planned: "neutral", transcript_ready: "info", memo_draft: "warning", completed: "success", archived: "neutral" } as const;
  return <StatusPill tone={tone[status]}>{t.meetingStatus[status]}</StatusPill>;
}

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  const tone = { draft: "neutral", needs_review: "warning", confirmed: "success", rejected: "danger" } as const;
  return <StatusPill tone={tone[status]}>{t.verification[status]}</StatusPill>;
}

export const priorityText: Record<Priority, string> = { low: "text-muted", medium: "text-warning", high: "text-danger", critical: "text-danger font-semibold" };

export function PriorityBadge({ priority }: { priority: Priority }) {
  return <span className={cn("text-xs whitespace-nowrap", priorityText[priority])}>{t.priority[priority]}</span>;
}

export function ActionStatusBadge({ status }: { status: ActionStatus }) {
  const tone = { open: "neutral", in_progress: "info", blocked: "danger", done: "success", cancelled: "neutral" } as const;
  return <StatusPill tone={tone[status]}>{t.actionStatus[status]}</StatusPill>;
}

export function TranslationStatusBadge({ status }: { status: TranslationStatus }) {
  const mark = { pending: "…", processing: "↻", done: "✓", failed: "✕" } as const;
  const color = { pending: "text-muted", processing: "text-info", done: "text-success", failed: "text-danger" } as const;
  return (
    <span className={cn("text-xs whitespace-nowrap", color[status])}>
      {mark[status]} {t.translationStatus[status]}
    </span>
  );
}

export function AiBadge({ ai }: { ai: boolean }) {
  return ai ? (
    <Badge tone="info" title={t.common.aiGenerated}>
      AI
    </Badge>
  ) : (
    <Badge title={t.common.humanEntered}>✎</Badge>
  );
}
