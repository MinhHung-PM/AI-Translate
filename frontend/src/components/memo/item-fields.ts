import type { ActionItem, Decision, Issue, Risk } from "@/lib/types";

export type ItemKind = "decisions" | "action-items" | "issues" | "risks";
export type AnyItem = Decision | ActionItem | Issue | Risk;

export interface FieldDef {
  name: string;
  label: string;
  type: "text" | "textarea" | "date" | "select" | "checkbox" | "member";
  options?: { value: string; label: string }[];
  required?: boolean;
}

/** Converts an item into editable string/boolean values for the form. */
export function toForm(item: AnyItem | null, fields: FieldDef[]): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {};
  for (const f of fields) {
    const raw = item ? (item as unknown as Record<string, unknown>)[f.name] : undefined;
    out[f.name] = f.type === "checkbox" ? Boolean(raw) : raw === null || raw === undefined ? "" : String(raw);
  }
  return out;
}

/** Converts form values into a PATCH/POST body (empty strings => null). */
export function fromForm(values: Record<string, string | boolean>, fields: FieldDef[]): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.name];
    if (f.type === "checkbox") body[f.name] = Boolean(v);
    else body[f.name] = typeof v === "string" && v.trim() === "" ? null : v;
  }
  return body;
}
