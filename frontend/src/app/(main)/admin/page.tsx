"use client";

import { useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, Input, PageHeader, Pagination, Select, Spinner, Table, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import type { AuditEvent, Division, DivisionAssignment, GlobalRole, Page, User } from "@/lib/types";

type Tab = "users" | "divisions" | "audit" | "health";
const ROLES: GlobalRole[] = ["member", "project_manager", "division_manager", "admin"];

export default function AdminPage() {
  const { session } = useSession();
  const [tab, setTab] = useState<Tab>("users");
  const [message, setMessage] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  if (session?.user.role !== "admin") return <Alert tone="danger">{t.errors.forbidden}</Alert>;

  async function act(fn: () => Promise<unknown>, ok?: string) {
    setMessage(null);
    try {
      await fn();
      if (ok) setMessage({ tone: "success", text: ok });
    } catch (err) {
      setMessage({ tone: "danger", text: errorMessage(err) });
    }
  }

  return (
    <>
      <PageHeader title={t.admin.title} subtitle={t.admin.noKeysNotice} />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { value: "users", label: t.admin.users },
          { value: "divisions", label: t.admin.divisions },
          { value: "audit", label: t.admin.audit },
          { value: "health", label: t.admin.health },
        ]}
      />
      {message && <Alert tone={message.tone} className="mb-3">{message.text}</Alert>}
      {tab === "users" && <UsersTab act={act} />}
      {tab === "divisions" && <DivisionsTab act={act} />}
      {tab === "audit" && <AuditTab />}
      {tab === "health" && <HealthTab act={act} />}
    </>
  );
}

type Act = (fn: () => Promise<unknown>, ok?: string) => Promise<void>;

function UsersTab({ act }: { act: Act }) {
  const [page, setPage] = useState(1);
  const users = useApi<Page<User>>("/admin/users", { page, page_size: 50 });
  const [form, setForm] = useState({ email: "", display_name: "", role: "member" as GlobalRole });
  return (
    <Card bodyClassName="p-0">
      <Table>
        <thead>
          <tr>
            <th>{t.admin.displayName}</th>
            <th>{t.admin.email}</th>
            <th>{t.admin.role}</th>
            <th>{t.admin.active}</th>
          </tr>
        </thead>
        <tbody>
          {users.data?.items.map((u) => (
            <tr key={u.id}>
              <td>{u.display_name}</td>
              <td className="text-muted">{u.email}</td>
              <td>
                <Select className="h-8 w-48 text-xs" value={u.role} aria-label={t.admin.role} onChange={(e) => void act(async () => (await api.patch(`/admin/users/${u.id}`, { role: e.target.value }), users.reload()))}>
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {t.roles[r]}
                    </option>
                  ))}
                </Select>
              </td>
              <td>
                <Checkbox label="" aria-label={t.admin.active} checked={u.is_active} onChange={(e) => void act(async () => (await api.patch(`/admin/users/${u.id}`, { is_active: e.target.checked }), users.reload()))} />
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="flex flex-wrap gap-2 border-t border-line p-3">
        <Input className="w-64" type="email" placeholder={t.admin.email} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} aria-label={t.admin.email} />
        <Input className="w-64" placeholder={t.admin.displayName} value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} aria-label={t.admin.displayName} />
        <Select className="w-48" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as GlobalRole })} aria-label={t.admin.role}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {t.roles[r]}
            </option>
          ))}
        </Select>
        <Button
          disabled={!form.email || !form.display_name}
          onClick={() => void act(async () => (await api.post("/admin/users", form), setForm({ email: "", display_name: "", role: "member" }), users.reload()))}
        >
          {t.admin.addUser}
        </Button>
      </div>
      {users.data && (
        <div className="px-3 pb-3">
          <Pagination page={page} pageSize={50} total={users.data.total} onChange={setPage} />
        </div>
      )}
    </Card>
  );
}

function DivisionsTab({ act }: { act: Act }) {
  const divisions = useApi<Division[]>("/admin/divisions");
  const assignments = useApi<DivisionAssignment[]>("/admin/division-assignments");
  const users = useApi<Page<User>>("/admin/users", { page_size: 100 });
  const [name, setName] = useState("");
  const [assign, setAssign] = useState({ user_id: "", division_id: "", can_view_transcripts: false });
  const managers = users.data?.items.filter((u) => u.role === "division_manager") ?? [];
  const nameOf = (id: string) => users.data?.items.find((u) => u.id === id)?.display_name ?? id;
  const divOf = (id: string) => divisions.data?.find((d) => d.id === id)?.name ?? id;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title={t.admin.divisions}>
        <ul className="mb-3 space-y-1 text-sm">
          {divisions.data?.map((d) => (
            <li key={d.id}>{d.name}</li>
          ))}
        </ul>
        <div className="flex gap-2">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t.admin.addDivision} aria-label={t.admin.addDivision} />
          <Button disabled={!name} onClick={() => void act(async () => (await api.post("/admin/divisions", { name }), setName(""), divisions.reload()))}>
            {t.common.add}
          </Button>
        </div>
      </Card>
      <Card title={t.admin.assignments}>
        <Table>
          <tbody>
            {assignments.data?.map((a) => (
              <tr key={a.id}>
                <td>{nameOf(a.user_id)}</td>
                <td>{divOf(a.division_id)}</td>
                <td>{a.can_view_transcripts ? <Badge tone="warning">{t.admin.canViewTranscripts}</Badge> : <Badge>{t.memo.restricted}</Badge>}</td>
                <td className="text-right">
                  <Button size="sm" variant="danger" onClick={() => void act(async () => (await api.del(`/admin/division-assignments/${a.id}`), assignments.reload()))}>
                    {t.common.delete}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <Select value={assign.user_id} onChange={(e) => setAssign({ ...assign, user_id: e.target.value })} aria-label={t.roles.division_manager}>
            <option value="">{t.roles.division_manager}…</option>
            {managers.map((u) => (
              <option key={u.id} value={u.id}>
                {u.display_name}
              </option>
            ))}
          </Select>
          <Select value={assign.division_id} onChange={(e) => setAssign({ ...assign, division_id: e.target.value })} aria-label={t.admin.divisions}>
            <option value="">{t.admin.divisions}…</option>
            {divisions.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
          <Checkbox label={t.admin.canViewTranscripts} checked={assign.can_view_transcripts} onChange={(e) => setAssign({ ...assign, can_view_transcripts: e.target.checked })} />
          <Button disabled={!assign.user_id || !assign.division_id} onClick={() => void act(async () => (await api.put("/admin/division-assignments", assign), assignments.reload()))}>
            {t.common.save}
          </Button>
        </div>
      </Card>
    </div>
  );
}

function AuditTab() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const events = useApi<Page<AuditEvent>>("/admin/audit-events", { page, page_size: 50, action });
  return (
    <Card bodyClassName="p-0">
      <div className="p-3">
        <Input className="max-w-xs" placeholder="action prefix (e.g. memo.)" value={action} onChange={(e) => (setAction(e.target.value), setPage(1))} aria-label="action" />
      </div>
      <Table>
        <tbody>
          {events.data?.items.map((e) => (
            <tr key={e.id}>
              <td className="w-40 text-xs whitespace-nowrap text-muted">{formatDateTime(e.created_at)}</td>
              <td className="font-mono text-xs">{e.action}</td>
              <td className="text-xs text-muted">
                {e.resource_type} {e.resource_id?.slice(0, 8)}
              </td>
              <td className="font-mono text-[11px] text-muted">{JSON.stringify(e.details)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      {events.data && (
        <div className="px-3 pb-3">
          <Pagination page={page} pageSize={50} total={events.data.total} onChange={setPage} />
        </div>
      )}
    </Card>
  );
}

function HealthTab({ act }: { act: Act }) {
  const health = useApi<{ database: string; jobs: Record<string, number>; recent_failures: { id: string; kind: string; error_code: string; finished_at: string }[]; active_sessions: number }>("/admin/health");
  if (!health.data) return <Spinner />;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title={t.admin.jobs}>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <dt className="text-muted">Database</dt>
          <dd>
            <Badge tone="success">{health.data.database}</Badge>
          </dd>
          <dt className="text-muted">Sessions</dt>
          <dd>{health.data.active_sessions}</dd>
          {Object.entries(health.data.jobs).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{(t.jobStatus as Record<string, string>)[k] ?? k}</dt>
              <dd className="tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
        <Button className="mt-3" onClick={() => void act(() => api.post("/admin/retention/run"), "OK")}>
          {t.admin.runRetention}
        </Button>
      </Card>
      <Card title="Recent failures" bodyClassName="p-0">
        <Table>
          <tbody>
            {health.data.recent_failures.map((f) => (
              <tr key={f.id}>
                <td className="font-mono text-xs">{f.kind}</td>
                <td className="font-mono text-xs">{f.error_code}</td>
                <td className="text-xs text-muted">{formatDateTime(f.finished_at)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}
