import { Badge } from "@/components/ui";
import { t } from "@/lib/i18n";
import type { ActionStatus, MeetingStatus, MemoStatus, Priority, TranslationStatus, VerificationStatus } from "@/lib/types";

export function MemoStatusBadge({ status }: { status: MemoStatus | null }) {
  if (!status) return <Badge>{t.memoStatus.none}</Badge>;
  const tone = { generating: "info", failed: "danger", draft: "neutral", in_review: "warning", approved: "success", rejected: "danger" } as const;
  return <Badge tone={tone[status]}>{t.memoStatus[status]}</Badge>;
}

export function MeetingStatusBadge({ status }: { status: MeetingStatus }) {
  const tone = { planned: "neutral", transcript_ready: "info", memo_draft: "warning", completed: "success", archived: "neutral" } as const;
  return <Badge tone={tone[status]}>{t.meetingStatus[status]}</Badge>;
}

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  const tone = { draft: "brand", needs_review: "warning", confirmed: "success", rejected: "neutral" } as const;
  return <Badge tone={tone[status]}>{t.verification[status]}</Badge>;
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  const tone = { low: "neutral", medium: "info", high: "warning", critical: "danger" } as const;
  return <Badge tone={tone[priority]}>{t.priority[priority]}</Badge>;
}

export function ActionStatusBadge({ status }: { status: ActionStatus }) {
  const tone = { open: "info", in_progress: "brand", blocked: "danger", done: "success", cancelled: "neutral" } as const;
  return <Badge tone={tone[status]}>{t.actionStatus[status]}</Badge>;
}

export function TranslationStatusBadge({ status }: { status: TranslationStatus }) {
  const tone = { pending: "neutral", processing: "info", done: "success", failed: "danger" } as const;
  return <Badge tone={tone[status]}>{t.translationStatus[status]}</Badge>;
}

export function AiBadge({ ai }: { ai: boolean }) {
  return ai ? <Badge tone="brand" title={t.common.aiGenerated}>AI</Badge> : <Badge title={t.common.humanEntered}>✎</Badge>;
}
