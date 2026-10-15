"use client";

import { useState } from "react";
import { Alert, Button, Checkbox, Dialog, Field, Input, Select, Textarea } from "@/components/ui";
import { t } from "@/lib/i18n";
import type { Member } from "@/lib/types";
import { fromForm, toForm, type AnyItem, type FieldDef } from "./item-fields";

interface Props {
  open: boolean;
  isNew: boolean;
  title: string;
  fields: FieldDef[];
  item: AnyItem | null;
  members: Member[];
  onClose: () => void;
  onSave: (body: Record<string, unknown>) => Promise<void>;
}

export function ItemEditor(props: Props) {
  // The form is remounted each time the dialog opens, so its state is
  // initialised from the item without syncing state inside an effect.
  return (
    <Dialog open={props.open} onClose={props.onClose} title={props.title} wide>
      {props.open && <EditorForm {...props} />}
    </Dialog>
  );
}

function EditorForm({ isNew, fields, item, members, onClose, onSave }: Props) {
  const [initial] = useState(() => toForm(item, fields));
  const [values, setValues] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const missing = fields.some((f) => f.required && !String(values[f.name] ?? "").trim());

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const body = fromForm(values, fields);
      // For edits send only changed fields, so tracking updates on an approved
      // memo do not touch locked content fields.
      if (!isNew) for (const key of Object.keys(body)) if (values[key] === initial[key]) delete body[key];
      await onSave(body);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : t.common.errorGeneric);
    } finally {
      setBusy(false);
    }
  }

  const set = (name: string, v: string | boolean) => setValues((prev) => ({ ...prev, [name]: v }));

  return (
    <>
      <div className="grid gap-3 md:grid-cols-2">
        {fields.map((f) => {
          const v = values[f.name];
          if (f.type === "checkbox")
            return <Checkbox key={f.name} label={f.label} checked={Boolean(v)} onChange={(e) => set(f.name, e.target.checked)} className="md:col-span-2" />;
          return (
            <Field key={f.name} label={f.label + (f.required ? " *" : "")} className={f.type === "textarea" ? "md:col-span-2" : undefined}>
              {(id) =>
                f.type === "textarea" ? (
                  <Textarea id={id} rows={3} value={String(v ?? "")} onChange={(e) => set(f.name, e.target.value)} />
                ) : f.type === "select" ? (
                  <Select id={id} value={String(v ?? "")} onChange={(e) => set(f.name, e.target.value)}>
                    {f.options?.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </Select>
                ) : f.type === "member" ? (
                  <Select id={id} value={String(v ?? "")} onChange={(e) => set(f.name, e.target.value)}>
                    <option value="">{t.common.none}</option>
                    {members.map((m) => (
                      <option key={m.user_id} value={m.user_id}>
                        {m.display_name}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Input id={id} type={f.type === "date" ? "date" : "text"} value={String(v ?? "")} onChange={(e) => set(f.name, e.target.value)} />
                )
              }
            </Field>
          );
        })}
      </div>
      {error && <Alert tone="danger" className="mt-3">{error}</Alert>}
      <div className="mt-4 flex justify-end gap-2 border-t border-line pt-3">
        <Button onClick={onClose}>{t.common.cancel}</Button>
        <Button variant="primary" onClick={() => void submit()} loading={busy} disabled={missing} data-testid="item-save">
          {t.common.save}
        </Button>
      </div>
    </>
  );
}
