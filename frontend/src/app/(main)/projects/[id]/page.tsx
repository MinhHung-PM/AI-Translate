"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, Field, Input, PageHeader, Select, Spinner, Table, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { useFeature } from "@/lib/session";
import type { GlossaryEntry, Language, Member, Project, ProjectRole } from "@/lib/types";

const LANGS: Language[] = ["ja", "vi", "en"];

function LangSelect({ value, onChange, id, disabled }: { value: Language; onChange: (l: Language) => void; id?: string; disabled?: boolean }) {
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value as Language)} disabled={disabled}>
      {LANGS.map((l) => (
        <option key={l} value={l}>
          {t.languages[l]}
        </option>
      ))}
    </Select>
  );
}

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const project = useApi<Project>(`/projects/${id}`);
  // Shared team site: one team account, no individual members to manage.
  const shared = useFeature("shared_mode");
  const members = useApi<Member[]>(shared ? null : `/projects/${id}/members`);
  const glossary = useApi<GlossaryEntry[]>(project.data?.permissions.view_summary ? `/projects/${id}/glossary` : null);
  const [edits, setEdits] = useState<Partial<Project>>({});
  const [message, setMessage] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState<ProjectRole>("member");
  const [term, setTerm] = useState({ source_term: "", preferred_translation: "", source_language: "ja" as Language, target_language: "vi" as Language, context: "" });

  const p = project.data;
  const form = p ? { ...p, ...edits } : null;
  const setForm = (next: Project) => setEdits(next);
  const canManage = Boolean(p && (p.permissions.manage || p.permissions.admin));
  const glossaryManage = Boolean(p?.permissions.manage);

  async function act(fn: () => Promise<unknown>, ok?: string) {
    setMessage(null);
    try {
      await fn();
      if (ok) setMessage({ tone: "success", text: ok });
    } catch (err) {
      setMessage({ tone: "danger", text: errorMessage(err) });
    }
  }

  if (project.error) return <Alert tone="danger">{errorMessage(project.error)}</Alert>;
  if (!p || !form) return <Spinner />;

  return (
    <>
      <PageHeader title={`${p.code} — ${p.name}`} subtitle={p.client_name} />
      {message && <Alert tone={message.tone} className="mb-3">{message.text}</Alert>}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={t.projects.settings}>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label={t.projects.name}>{(fid) => <Input id={fid} value={form.name} disabled={!canManage} onChange={(e) => setForm({ ...form, name: e.target.value })} />}</Field>
            <Field label={t.projects.client}>
              {(fid) => <Input id={fid} value={form.client_name ?? ""} disabled={!canManage} onChange={(e) => setForm({ ...form, client_name: e.target.value })} />}
            </Field>
            <Field label={t.meetingForm.sourceLanguage}>
              {(fid) => <LangSelect id={fid} value={form.default_source_language} disabled={!canManage} onChange={(l) => setForm({ ...form, default_source_language: l })} />}
            </Field>
            <Field label={t.meetingForm.targetLanguage}>
              {(fid) => <LangSelect id={fid} value={form.default_target_language} disabled={!canManage} onChange={(l) => setForm({ ...form, default_target_language: l })} />}
            </Field>
            <Field label={t.meetingForm.memoLanguage}>
              {(fid) => <LangSelect id={fid} value={form.default_memo_language} disabled={!canManage} onChange={(l) => setForm({ ...form, default_memo_language: l })} />}
            </Field>
            <Field label={t.projects.retention}>
              {(fid) => (
                <Input id={fid} type="number" min={1} max={3650} value={form.retention_days} disabled={!canManage} onChange={(e) => setForm({ ...form, retention_days: Number(e.target.value) })} />
              )}
            </Field>
            <Field label={t.projects.instructions} className="md:col-span-2">
              {(fid) => (
                <Textarea id={fid} value={form.translation_instructions ?? ""} disabled={!canManage} onChange={(e) => setForm({ ...form, translation_instructions: e.target.value })} />
              )}
            </Field>
            <Field label={t.projects.description} className="md:col-span-2">
              {(fid) => <Textarea id={fid} value={form.description ?? ""} disabled={!canManage} onChange={(e) => setForm({ ...form, description: e.target.value })} />}
            </Field>
          </div>
          {canManage && (
            <Button
              variant="primary"
              className="mt-3"
              onClick={() =>
                void act(async () => {
                  setEdits({});
                  project.setData(
                    await api.patch<Project>(`/projects/${id}`, {
                      name: form.name,
                      client_name: form.client_name || null,
                      description: form.description || null,
                      retention_days: form.retention_days,
                      default_source_language: form.default_source_language,
                      default_target_language: form.default_target_language,
                      default_memo_language: form.default_memo_language,
                      translation_instructions: form.translation_instructions || null,
                    }),
                  );
                }, t.common.save)
              }
            >
              {t.common.save}
            </Button>
          )}
        </Card>

        {!shared && (
        <Card title={`${t.projects.members} (${members.data?.length ?? 0})`}>
          <Table>
            <tbody>
              {members.data?.map((m) => (
                <tr key={m.user_id}>
                  <td>
                    {m.display_name}
                    <p className="text-xs text-muted">{m.email}</p>
                  </td>
                  <td>
                    <Badge tone={m.role === "manager" ? "brand" : "neutral"}>{t.roles[m.role]}</Badge>
                  </td>
                  <td className="text-right">
                    {canManage && (
                      <Button size="sm" variant="danger" onClick={() => void act(async () => (await api.del(`/projects/${id}/members/${m.user_id}`), members.reload()))}>
                        {t.common.delete}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
          {canManage && (
            <div className="mt-3 flex flex-wrap gap-2">
              <Input className="flex-1" type="email" placeholder={t.projects.addMember} value={memberEmail} onChange={(e) => setMemberEmail(e.target.value)} aria-label={t.projects.addMember} />
              <Select className="w-40" value={memberRole} onChange={(e) => setMemberRole(e.target.value as ProjectRole)} aria-label={t.admin.role}>
                <option value="member">{t.roles.member}</option>
                <option value="manager">{t.roles.manager}</option>
              </Select>
              <Button
                disabled={!memberEmail}
                onClick={() =>
                  void act(async () => {
                    await api.post(`/projects/${id}/members`, { email: memberEmail, role: memberRole });
                    setMemberEmail("");
                    await members.reload();
                  })
                }
              >
                {t.common.add}
              </Button>
            </div>
          )}
        </Card>
        )}

        <Card title={t.projects.glossary} className="xl:col-span-2">
          <Table>
            <thead>
              <tr>
                <th>{t.projects.sourceTerm}</th>
                <th>{t.projects.preferred}</th>
                <th>{t.projects.pair}</th>
                <th>{t.projects.context}</th>
                <th>{t.projects.active}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {glossary.data?.map((g) => (
                <tr key={g.id}>
                  <td>{g.source_term}</td>
                  <td>{g.preferred_translation}</td>
                  <td className="text-xs">
                    {g.source_language} → {g.target_language}
                  </td>
                  <td className="text-xs text-muted">{g.context}</td>
                  <td>
                    <Checkbox
                      label=""
                      aria-label={t.projects.active}
                      checked={g.is_active}
                      disabled={!glossaryManage}
                      onChange={(e) => void act(async () => (await api.patch(`/projects/${id}/glossary/${g.id}`, { is_active: e.target.checked }), glossary.reload()))}
                    />
                  </td>
                  <td className="text-right">
                    {glossaryManage && (
                      <Button size="sm" variant="danger" onClick={() => void act(async () => (await api.del(`/projects/${id}/glossary/${g.id}`), glossary.reload()))}>
                        {t.common.delete}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
          {glossaryManage && (
            <div className="mt-3 grid gap-2 md:grid-cols-6">
              <Input placeholder={t.projects.sourceTerm} value={term.source_term} onChange={(e) => setTerm({ ...term, source_term: e.target.value })} aria-label={t.projects.sourceTerm} />
              <Input placeholder={t.projects.preferred} value={term.preferred_translation} onChange={(e) => setTerm({ ...term, preferred_translation: e.target.value })} aria-label={t.projects.preferred} />
              <LangSelect value={term.source_language} onChange={(l) => setTerm({ ...term, source_language: l })} />
              <LangSelect value={term.target_language} onChange={(l) => setTerm({ ...term, target_language: l })} />
              <Input placeholder={t.projects.context} value={term.context} onChange={(e) => setTerm({ ...term, context: e.target.value })} aria-label={t.projects.context} />
              <Button
                disabled={!term.source_term || !term.preferred_translation}
                onClick={() =>
                  void act(async () => {
                    await api.post(`/projects/${id}/glossary`, { ...term, context: term.context || null });
                    setTerm({ ...term, source_term: "", preferred_translation: "", context: "" });
                    await glossary.reload();
                  })
                }
              >
                {t.common.add}
              </Button>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
