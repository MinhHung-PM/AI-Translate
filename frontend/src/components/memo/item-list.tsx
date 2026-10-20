"use client";

import { useMemo, useState } from "react";
import { Badge, Button, cn } from "@/components/ui";
import { ActionStatusBadge, PriorityBadge, VerificationBadge } from "@/components/shared/status";
import { formatDate } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { ActionItem, Decision, Issue, Member, Risk } from "@/lib/types";
import { DEFAULTS, ITEM_FIELDS, createFields } from "./item-config";
import { ItemEditor } from "./item-editor";
import type { AnyItem, ItemKind } from "./item-fields";
import { SourceLink, SourceRefs } from "./source-refs";

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
        <span className={cn(a.is_overdue && "font-medium text-danger")}>
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
  const [openSource, setOpenSource] = useState<string | null>(null);
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
    <div className="flex flex-col gap-2" data-testid={`items-${kind}`}>
      {items.length === 0 && <p className="py-1 text-sm text-muted">{t.memo.noItems}</p>}
      {items.map((item) => {
        const v = item.verification_status;
        const open = openSource === item.id;
        return (
          <article
            key={item.id}
            className={cn(
              "flex flex-col gap-2 rounded-xl border p-3",
              v === "needs_review" ? "border-warning" : "border-line",
              v === "confirmed" && "bg-surface-2",
            )}
            data-testid="memo-item"
          >
            <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
              <p className={cn("min-w-52 flex-1 text-[15px] leading-snug", v === "rejected" && "text-muted line-through")}>
                <span className="mr-1.5 font-mono text-[11px] text-subtle">{item.code}</span>
                {itemText(kind, item)}
              </p>
              <span className="flex flex-wrap items-center gap-1.5">
                {item.ai_generated ? (
                  <Badge tone="info" title={t.memo.fields.confidence}>
                    AI{item.confidence && ` · ${t.confidence[item.confidence].toLowerCase()}`}
                  </Badge>
                ) : (
                  <Badge title={t.common.humanEntered}>✎</Badge>
                )}
                <VerificationBadge status={v} />
              </span>
            </div>
            <Details kind={kind} item={item} />
            {item.review_note && <p className="text-xs text-warning">⚠ {item.review_note}</p>}
            <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5 text-xs">
              {item.sources.length > 0 ? (
                <span className="flex items-center gap-1.5">
                  <SourceLink meetingId={meetingId} source={item.sources[0]} />
                  {item.sources.some((src) => src.excerpt) && (
                    <button type="button" onClick={() => setOpenSource(open ? null : item.id)} aria-expanded={open} className="text-info">
                      {open ? `▴ ${t.memo.hideSource}` : `▾ ${t.memo.showSource}`}
                    </button>
                  )}
                </span>
              ) : (
                <span className="text-muted">
                  {t.common.source}: {t.common.none}
                </span>
              )}
              <span className="flex-1" />
              {canEditItem && v !== "confirmed" && (
                <Button size="sm" variant="primary" className="h-7 px-3 text-xs" onClick={() => void verify(item, "confirmed")} loading={busyId === item.id} data-testid="confirm-item">
                  ✓ {t.memo.confirmItem}
                </Button>
              )}
              {canEditItem && v !== "rejected" && (
                <button type="button" className="text-muted hover:text-ink disabled:opacity-50" onClick={() => void verify(item, "rejected")} disabled={busyId === item.id}>
                  {t.memo.rejectItem}
                </button>
              )}
              {canEditItem && (
                <button type="button" className="text-ink hover:underline" onClick={() => setEditing(item)}>
                  {t.common.edit}
                </button>
              )}
              {canEditContent && (
                <button type="button" className="text-danger hover:underline" onClick={() => void onDelete(kind, item.id)}>
                  {t.common.delete}
                </button>
              )}
            </div>
            {open && <SourceRefs meetingId={meetingId} sources={item.sources} />}
          </article>
        );
      })}
      {canEditContent && (
        <button type="button" onClick={() => setCreating(true)} className="self-start text-[13px] text-info">
          + {addLabel}
        </button>
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
