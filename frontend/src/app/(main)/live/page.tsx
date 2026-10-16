"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Card, EmptyState, Field, Input, PageHeader, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { Language, Meeting, Page, Project } from "@/lib/types";

const LANGS: Language[] = ["ja", "vi", "en"];

/** Shortcut to live audio translation: create a meeting in one step and open
 * its live capture screen (Trực tiếp → Thu âm trực tiếp). */
export default function LiveTranslatePage() {
  const router = useRouter();
  const { data: projects } = useApi<Page<Project>>("/projects", { page_size: 100 });
  const { data: recent } = useApi<Page<Meeting>>("/meetings", { page: 1, page_size: 5, sort: "scheduled_desc" });
  const [projectId, setProjectId] = useState("");
  const [title, setTitle] = useState("");
  const [source, setSource] = useState<Language | "">("");
  const [target, setTarget] = useState<Language | "">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const contributable = projects?.items.filter((p) => p.permissions.contribute) ?? [];
  const project = contributable.find((p) => p.id === projectId) ?? contributable[0];
  const src = source || project?.default_source_language || "ja";
  const tgt = target || project?.default_target_language || "vi";

  async function startNow() {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      const now = new Date();
      const meeting = await api.post<Meeting>("/meetings", {
        project_id: project.id,
        title: title.trim() || `${t.liveTranslate.defaultTitle} ${now.toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })}`,
        meeting_type: "client_meeting",
        scheduled_at: now.toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Tokyo",
        platform: "manual_import",
        source_language: src,
        target_language: tgt,
        memo_language: tgt,
        participants: [],
      });
      router.push(`/meetings/${meeting.id}/live`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  if (!projects) return <Spinner label={t.common.loading} />;

  return (
    <>
      <PageHeader title={t.liveTranslate.title} subtitle={t.liveTranslate.subtitle} />
      {contributable.length === 0 ? (
        <EmptyState title={t.meetingForm.noProjects} />
      ) : (
        <Card title={t.liveTranslate.quickStart} className="mb-4">
          <div className="grid gap-3 md:grid-cols-4" data-testid="live-quick-start">
            <Field label={t.meetingForm.project}>
              {(id) => (
                <Select id={id} value={project?.id ?? ""} onChange={(e) => setProjectId(e.target.value)} data-testid="live-project">
                  {contributable.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.code} — {p.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t.liveTranslate.titleLabel}>
              {(id) => <Input id={id} value={title} maxLength={300} placeholder={t.liveTranslate.titlePlaceholder} onChange={(e) => setTitle(e.target.value)} />}
            </Field>
            <Field label={t.liveTranslate.spoken}>
              {(id) => (
                <Select id={id} value={src} onChange={(e) => setSource(e.target.value as Language)}>
                  {LANGS.map((l) => (
                    <option key={l} value={l}>
                      {t.languages[l]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t.liveTranslate.translateTo}>
              {(id) => (
                <Select id={id} value={tgt} onChange={(e) => setTarget(e.target.value as Language)}>
                  {LANGS.map((l) => (
                    <option key={l} value={l}>
                      {t.languages[l]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>
          <p className="mt-3 text-xs text-muted">{t.liveTranslate.howItWorks}</p>
          {error && <Alert tone="danger" className="mt-3">{error}</Alert>}
          <Button variant="primary" className="mt-3" onClick={() => void startNow()} loading={busy} data-testid="live-start-now">
            {t.liveTranslate.startNow}
          </Button>
        </Card>
      )}

      {recent && recent.items.length > 0 && (
        <Card title={t.liveTranslate.existing}>
          <ul className="divide-y divide-line text-sm">
            {recent.items.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-3 py-2">
                <span className="truncate">
                  {m.title} <span className="text-xs text-muted">· {formatDateTime(m.scheduled_at, m.timezone)}</span>
                </span>
                <Link href={`/meetings/${m.id}/live`} className="text-sm whitespace-nowrap text-brand-700 underline">
                  {t.liveTranslate.openLive}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
