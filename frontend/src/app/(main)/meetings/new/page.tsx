"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { Alert, Badge, Button, Card, EmptyState, Field, Input, PageHeader, Select, Textarea } from "@/components/ui";
import { useProjects } from "@/components/shared/project-select";
import { api } from "@/lib/api";
import { errorMessage, zonedLocalToIso } from "@/lib/format";
import { parseParticipants } from "@/lib/participants";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { ConnectorStatus, Meeting, MeetingPlatform } from "@/lib/types";

const LANGS = ["ja", "vi", "en"] as const;
const TIMEZONES = ["Asia/Tokyo", "Asia/Ho_Chi_Minh", "UTC", "Asia/Singapore", "America/New_York", "Europe/London"];

const schema = z.object({
  title: z.string().trim().min(1, t.common.required).max(300),
  project_id: z.string().min(1, t.common.required),
  meeting_type: z.enum(["client_meeting", "internal", "requirements", "review", "steering", "standup", "other"]),
  scheduled_local: z.string().min(1, t.common.required),
  timezone: z.string().min(1),
  participants: z.string().max(5000),
  source_language: z.enum(["", ...LANGS]),
  target_language: z.enum(LANGS),
  memo_language: z.enum(LANGS),
  platform: z.enum(["manual_import", "teams", "zoom", "google_meet"]),
  meeting_url: z.union([z.literal(""), z.url({ protocol: /^https?$/ })]),
  objective: z.string().max(10000),
  custom_instructions: z.string().max(2000),
});

type FormValues = z.infer<typeof schema>;

function nowLocal(): string {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
}

export default function NewMeetingPage() {
  const router = useRouter();
  const { data: projects } = useProjects();
  const { data: connectors } = useApi<ConnectorStatus[]>("/connectors");
  const [error, setError] = useState<string | null>(null);
  const contributable = projects?.items.filter((p) => p.permissions.contribute) ?? [];

  const { register, handleSubmit, control, setValue, formState } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: "",
      project_id: "",
      meeting_type: "client_meeting",
      scheduled_local: nowLocal(),
      timezone: "Asia/Tokyo",
      participants: "",
      source_language: "",
      target_language: "vi",
      memo_language: "vi",
      platform: "manual_import",
      meeting_url: "",
      objective: "",
      custom_instructions: "",
    },
  });
  const projectId = useWatch({ control, name: "project_id" });
  const platform = useWatch({ control, name: "platform" }) as MeetingPlatform;
  const connector = connectors?.find((c) => c.key === platform);

  // Apply project language defaults when a project is chosen.
  useEffect(() => {
    const p = contributable.find((x) => x.id === projectId);
    if (!p) return;
    setValue("source_language", p.default_source_language);
    setValue("target_language", p.default_target_language);
    setValue("memo_language", p.default_memo_language);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    if (!projectId && contributable.length === 1) setValue("project_id", contributable[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contributable.length]);

  async function onSubmit(values: FormValues) {
    setError(null);
    try {
      const meeting = await api.post<Meeting>("/meetings", {
        project_id: values.project_id,
        title: values.title,
        meeting_type: values.meeting_type,
        scheduled_at: zonedLocalToIso(values.scheduled_local, values.timezone),
        timezone: values.timezone,
        platform: values.platform,
        meeting_url: values.meeting_url || null,
        objective: values.objective || null,
        custom_instructions: values.custom_instructions || null,
        source_language: values.source_language || null,
        target_language: values.target_language,
        memo_language: values.memo_language,
        participants: parseParticipants(values.participants),
      });
      router.push(`/meetings/${meeting.id}`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const errors = formState.errors;
  if (projects && contributable.length === 0) {
    return (
      <>
        <PageHeader title={t.meetingForm.title} />
        <EmptyState title={t.meetingForm.noProjects} />
      </>
    );
  }

  return (
    <>
      <PageHeader title={t.meetingForm.title} />
      <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4 lg:grid-cols-3" noValidate>
        <Card title={t.meetingForm.title} className="lg:col-span-2">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label={t.meetingForm.meetingTitle} error={errors.title?.message} className="md:col-span-2">
              {(id) => <Input id={id} {...register("title")} aria-invalid={!!errors.title} />}
            </Field>
            <Field label={t.meetingForm.project} error={errors.project_id?.message}>
              {(id) => (
                <Select id={id} {...register("project_id")}>
                  <option value="">{t.meetingForm.selectProject}</option>
                  {contributable.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.code} — {p.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t.meetingForm.type}>
              {(id) => (
                <Select id={id} {...register("meeting_type")}>
                  {Object.entries(t.meetingType).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t.meetingForm.date} error={errors.scheduled_local?.message}>
              {(id) => <Input id={id} type="datetime-local" {...register("scheduled_local")} />}
            </Field>
            <Field label={t.meetingForm.timezone}>
              {(id) => (
                <Select id={id} {...register("timezone")}>
                  {TIMEZONES.map((tz) => (
                    <option key={tz} value={tz}>
                      {tz}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t.meetingForm.sourceLanguage}>
              {(id) => (
                <Select id={id} {...register("source_language")}>
                  <option value="">{t.languages.auto}</option>
                  {LANGS.map((l) => (
                    <option key={l} value={l}>
                      {t.languages[l]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t.meetingForm.targetLanguage}>
              {(id) => (
                <Select id={id} {...register("target_language")}>
                  {LANGS.map((l) => (
                    <option key={l} value={l}>
                      {t.languages[l]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t.meetingForm.memoLanguage}>
              {(id) => (
                <Select id={id} {...register("memo_language")}>
                  {LANGS.map((l) => (
                    <option key={l} value={l}>
                      {t.languages[l]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t.meetingForm.participants} hint={t.meetingForm.participantsHint} className="md:col-span-2">
              {(id) => <Textarea id={id} rows={4} {...register("participants")} placeholder={"田中 | Sakura Logistics\nNguyễn Văn An | Dev team"} />}
            </Field>
            <Field label={t.meetingForm.objective} className="md:col-span-2">
              {(id) => <Textarea id={id} rows={2} {...register("objective")} />}
            </Field>
            <Field label={t.meetingForm.instructions} hint={t.meetingForm.instructionsHint} className="md:col-span-2">
              {(id) => <Textarea id={id} rows={2} {...register("custom_instructions")} />}
            </Field>
          </div>
        </Card>

        <div className="space-y-4">
          <Card title={t.meetingForm.platform}>
            <div className="space-y-3">
              <Field label={t.meetingForm.platform}>
                {(id) => (
                  <Select id={id} {...register("platform")}>
                    {(["manual_import", "teams", "zoom", "google_meet"] as const).map((p) => (
                      <option key={p} value={p}>
                        {t.platform[p]}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              {connector && (
                <div className="flex items-start gap-2 text-sm">
                  <Badge tone={connector.state === "not_configured" ? "warning" : "success"}>
                    {connector.state === "not_configured" ? t.platform.not_configured : t.platform.available}
                  </Badge>
                </div>
              )}
              {platform !== "manual_import" && <Alert tone="warning">{t.platform.notConfiguredHint}</Alert>}
              <Field label={t.meetingForm.url} error={errors.meeting_url?.message}>
                {(id) => <Input id={id} type="url" {...register("meeting_url")} placeholder="https://" />}
              </Field>
            </div>
          </Card>
          {error && <Alert tone="danger">{error}</Alert>}
          <Button type="submit" variant="primary" className="w-full" loading={formState.isSubmitting}>
            {t.meetingForm.submit}
          </Button>
        </div>
      </form>
    </>
  );
}
