import { t } from "@/lib/i18n";
import type { FieldDef, ItemKind } from "./item-fields";

const opts = (rec: Record<string, string>) => Object.entries(rec).map(([value, label]) => ({ value, label }));
const f = t.memo.fields;

const owner: FieldDef[] = [
  { name: "owner_text", label: f.owner, type: "text" },
  { name: "owner_user_id", label: f.projectMember, type: "member" },
];
const review: FieldDef = { name: "review_note", label: f.reviewNote, type: "textarea" };

export const ITEM_FIELDS: Record<ItemKind, FieldDef[]> = {
  decisions: [{ name: "statement", label: f.statement, type: "textarea", required: true }, ...owner, review],
  "action-items": [
    { name: "description", label: f.description, type: "textarea", required: true },
    ...owner,
    { name: "due_date", label: f.due, type: "date" },
    { name: "due_text", label: f.dueText, type: "text" },
    { name: "priority", label: f.priority, type: "select", options: opts(t.priority) },
    { name: "status", label: f.status, type: "select", options: opts(t.actionStatus) },
    { name: "due_needs_confirmation", label: f.dueNeedsConfirm, type: "checkbox" },
    review,
  ],
  issues: [
    { name: "description", label: f.description, type: "textarea", required: true },
    { name: "impact", label: f.impact, type: "textarea" },
    ...owner,
    { name: "status", label: f.status, type: "select", options: opts(t.issueStatus) },
    { name: "priority", label: f.priority, type: "select", options: opts(t.priority) },
    { name: "follow_up", label: f.followUp, type: "textarea" },
    review,
  ],
  risks: [
    { name: "description", label: f.description, type: "textarea", required: true },
    { name: "probability", label: f.probability, type: "select", options: opts(t.likelihood) },
    { name: "severity", label: f.severity, type: "select", options: opts(t.priority) },
    { name: "impact", label: f.impact, type: "textarea" },
    { name: "mitigation", label: f.mitigation, type: "textarea" },
    ...owner,
    review,
  ],
};

/** Fields allowed when creating (status/verification are server-controlled). */
export function createFields(kind: ItemKind): FieldDef[] {
  return ITEM_FIELDS[kind].filter((x) => !["status", "due_needs_confirmation", "review_note"].includes(x.name) || kind === "issues");
}

export const DEFAULTS: Record<ItemKind, Record<string, string>> = {
  decisions: {},
  "action-items": { priority: "medium", status: "open" },
  issues: { status: "open", priority: "medium" },
  risks: { probability: "unknown", severity: "medium" },
};
