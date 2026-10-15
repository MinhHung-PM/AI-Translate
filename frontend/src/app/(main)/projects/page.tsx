"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert, Badge, Button, Card, Dialog, EmptyState, Field, Input, PageHeader, Spinner, Table, Textarea } from "@/components/ui";
import { useProjects } from "@/components/shared/project-select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import type { Project } from "@/lib/types";

export default function ProjectsPage() {
  const { session } = useSession();
  const { data, error, loading, reload } = useProjects();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", client_name: "", description: "", retention_days: "365" });
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canCreate = session?.user.role === "admin" || session?.user.role === "project_manager";

  async function create() {
    setBusy(true);
    setFormError(null);
    try {
      await api.post<Project>("/projects", {
        code: form.code,
        name: form.name,
        client_name: form.client_name || null,
        description: form.description || null,
        retention_days: Number(form.retention_days),
      });
      setOpen(false);
      setForm({ code: "", name: "", client_name: "", description: "", retention_days: "365" });
      await reload();
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={t.projects.title}
        actions={
          canCreate && (
            <Button variant="primary" onClick={() => setOpen(true)} data-testid="create-project">
              {t.projects.create}
            </Button>
          )
        }
      />
      {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      {loading && !data && <Spinner />}
      {data && (
        <Card bodyClassName="p-0">
          {data.items.length === 0 ? (
            <div className="p-4">
              <EmptyState title={t.projects.empty} />
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>{t.projects.code}</th>
                  <th>{t.projects.name}</th>
                  <th>{t.projects.client}</th>
                  <th>{t.projects.defaults}</th>
                  <th>{t.projects.myRole}</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.id}>
                    <td className="font-mono text-xs">{p.code}</td>
                    <td>
                      <Link href={`/projects/${p.id}`} className="font-medium text-brand-700 hover:underline">
                        {p.name}
                      </Link>
                    </td>
                    <td className="text-muted">{p.client_name ?? t.common.none}</td>
                    <td className="text-xs text-muted">
                      {p.default_source_language} → {p.default_target_language} · memo {p.default_memo_language}
                    </td>
                    <td>{p.my_role ? <Badge tone={p.my_role === "manager" ? "brand" : "neutral"}>{t.roles[p.my_role]}</Badge> : <Badge>{p.permissions.view_summary ? t.roles.division_manager : t.roles.admin}</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      )}
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={t.projects.create}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>{t.common.cancel}</Button>
            <Button variant="primary" onClick={() => void create()} loading={busy} disabled={!form.code || !form.name} data-testid="project-submit">
              {t.common.save}
            </Button>
          </>
        }
      >
        <div className="grid gap-3 md:grid-cols-2">
          <Field label={`${t.projects.code} *`} hint="A-Z, 0-9, -, _">
            {(id) => <Input id={id} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} data-testid="project-code" />}
          </Field>
          <Field label={`${t.projects.name} *`}>
            {(id) => <Input id={id} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="project-name" />}
          </Field>
          <Field label={t.projects.client}>{(id) => <Input id={id} value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} />}</Field>
          <Field label={t.projects.retention}>
            {(id) => <Input id={id} type="number" min={1} max={3650} value={form.retention_days} onChange={(e) => setForm({ ...form, retention_days: e.target.value })} />}
          </Field>
          <Field label={t.projects.description} className="md:col-span-2">
            {(id) => <Textarea id={id} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />}
          </Field>
        </div>
        {formError && <Alert tone="danger" className="mt-3">{formError}</Alert>}
      </Dialog>
    </>
  );
}
