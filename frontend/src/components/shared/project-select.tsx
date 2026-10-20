"use client";

import { Select } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { Page, Project } from "@/lib/types";

export function useProjects() {
  return useApi<Page<Project>>("/projects", { page_size: 100 });
}

export function ProjectFilter({ value, onChange, id, className }: { value: string; onChange: (v: string) => void; id?: string; className?: string }) {
  const { data } = useProjects();
  return (
    <Select id={id} className={className} value={value} onChange={(e) => onChange(e.target.value)} aria-label={t.meetingForm.project}>
      <option value="">{t.common.all}</option>
      {data?.items.map((p) => (
        <option key={p.id} value={p.id}>
          {p.code} — {p.name}
        </option>
      ))}
    </Select>
  );
}
