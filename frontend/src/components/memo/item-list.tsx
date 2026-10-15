"use client";

import { useMemo, useState } from "react";
import { Badge, Button, EmptyState, cn } from "@/components/ui";
import { ActionStatusBadge, AiBadge, PriorityBadge, VerificationBadge } from "@/components/shared/status";
import { formatDate } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { ActionItem, Decision, Issue, Member, Risk } from "@/lib/types";
import { DEFAULTS, ITEM_FIELDS, createFields } from "./item-config";
import { ItemEditor } from "./item-editor";
import type { AnyItem, ItemKind } from "./item-fields";
import { SourceRefs } from "./source-refs";

interface Props {
  kind: ItemKind;
  items: AnyItem[];
  meetingId: string;
  members: Member[];
  canEditContent: boolean;
  canTrack: boolean;
  addLabel: string;
  onCreate: (kind: ItemKind, body: Record<string, unknown>) => Promise<void>;
  onPatch: (kind: ItemKind, id: string, body: Record<string, unknown>) => Promise<void>;
  onDelete: (kind: ItemKind, id: string) => Promise<void>;
}

function itemText(kind: ItemKind, item: AnyItem): string {
  return kind === "decisions" ? (item as Decision).statement : (item as ActionItem | Issue | Risk).description;
}

function Details({ kind, item }: { kind: ItemKind; item: AnyItem }) {
  const f = t.memo.fields;
  const owner = item.owner_text ?? t.common.none;
  if (kind === "action-items") {
    const a = item as ActionItem;
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
        <span>
          {f.owner}: <b className="font-medium text-ink">{owner}</b>
        </span>
        <span className={cn(a.is_overdue && "font-medium text-red-700")}>
          {f.due}: {a.due_date ? formatDate(a.due_date) : t.common.none}
          {a.due_text && ` (“${a.due_text}”)`}
        </span>
        {a.due_needs_confirmation && <Badge tone="warning">{f.dueNeedsConfirm}</Badge>}
        <PriorityBadge priority={a.priority} />
        <ActionStatusBadge status={a.status} />
      </div>
    );
  }
  if (kind === "issues") {
    const i = item as Issue;
    return (
      <div className="space-y-0.5 text-xs text-muted">
        <div className="flex flex-wrap gap-x-3">
          <span>
            {f.owner}: {owner}
          </span>
          <PriorityBadge priority={i.priority} />
          <Badge>{t.issueStatus[i.status]}</Badge>
        </div>
        {i.impact && (
          <p>
            {f.impact}: {i.impact}
          </p>
        )}
        {i.follow_up && (
          <p>
            {f.followUp}: {i.follow_up}
          </p>
        )}
      </div>
    );
  }
  if (kind === "risks") {
    const r = item as Risk;
    return (
      <div className="space-y-0.5 text-xs text-muted">
        <div className="flex flex-wrap gap-x-3">
          <span>
            {f.probability}: {t.likelihood[r.probability]}
          </span>
          <span>
            {f.severity}: <PriorityBadge priority={r.severity} />
          </span>
          <span>
            {f.owner}: {owner}
          </span>
        </div>
        {r.impact && (
          <p>
            {f.impact}: {r.impact}
          </p>
        )}
        {r.mitigation && (
          <p>
            {f.mitigation}: {r.mitigation}
          </p>
        )}
      </div>
    );
  }
  return (
    <p className="text-xs text-muted">
      {f.owner}: {owner}
    </p>
  );
}

export function ItemList({ kind, items, meetingId, members, canEditContent, canTrack, addLabel, onCreate, onPatch, onDelete }: Props) {
  const [editing, setEditing] = useState<AnyItem | null>(null);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const canEditItem = kind === "action-items" ? canTrack : canEditContent;
  const newFields = useMemo(() => createFields(kind), [kind]);

  async function verify(item: AnyItem, status: "confirmed" | "rejected") {
    setBusyId(item.id);
    try {
      await onPatch(kind, item.id, { verification_status: status });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-2" data-testid={`items-${kind}`}>
      {items.length === 0 && <EmptyState title={t.memo.noItems} />}
      {items.map((item) => (
        <article
          key={item.id}
          className={cn("rounded-md border border-line p-3", item.verification_status === "rejected" && "opacity-60", item.verification_status === "needs_review" && "border-amber-300 bg-amber-50/40")}
          data-testid="memo-item"
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-xs text-muted">{item.code}</span>
                <AiBadge ai={item.ai_generated} />
                <VerificationBadge status={item.verification_status} />
                {item.confidence && <Badge title={t.memo.fields.confidence}>{t.confidence[item.confidence]}</Badge>}
              </div>
              <p className={cn("text-sm", item.verification_status === "rejected" && "line-through")}>{itemText(kind, item)}</p>
              <div className="mt-1">
                <Details kind={kind} item={item} />
              </div>
              {item.review_note && <p className="mt-1 text-xs text-amber-800">⚠ {item.review_note}</p>}
              <SourceRefs meetingId={meetingId} sources={item.sources} />
            </div>
            <div className="flex shrink-0 flex-wrap gap-1">
              {canEditItem && item.verification_status !== "confirmed" && (
                <Button size="sm" variant="primary" onClick={() => void verify(item, "confirmed")} loading={busyId === item.id} data-testid="confirm-item">
                  {t.memo.confirmItem}
                </Button>
              )}
              {canEditItem && item.verification_status !== "rejected" && (
                <Button size="sm" onClick={() => void verify(item, "rejected")} disabled={busyId === item.id}>
                  {t.memo.rejectItem}
                </Button>
              )}
              {canEditItem && (
                <Button size="sm" variant="ghost" onClick={() => setEditing(item)}>
                  {t.common.edit}
                </Button>
              )}
              {canEditContent && (
                <Button size="sm" variant="danger" onClick={() => void onDelete(kind, item.id)}>
                  {t.common.delete}
                </Button>
              )}
            </div>
          </div>
        </article>
      ))}
      {canEditContent && (
        <Button size="sm" onClick={() => setCreating(true)}>
          + {addLabel}
        </Button>
      )}
      <ItemEditor
        open={editing !== null}
        isNew={false}
        title={`${t.common.edit} ${editing?.code ?? ""}`}
        fields={ITEM_FIELDS[kind]}
        item={editing}
        members={members}
        onClose={() => setEditing(null)}
        onSave={(body) => (editing ? onPatch(kind, editing.id, body) : Promise.resolve())}
      />
      <ItemEditor
        open={creating}
        isNew
        title={addLabel}
        fields={newFields}
        item={DEFAULTS[kind] as unknown as AnyItem}
        members={members}
        onClose={() => setCreating(false)}
        onSave={(body) => onCreate(kind, body)}
      />
    </div>
  );
}
