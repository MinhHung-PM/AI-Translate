"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert, Badge, Button, Field, Input, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import { useApi, useJob } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { AvailableMeeting, CapabilityName, ConnectionView, ExternalSource, ExternalTranscriptStatus, Job, PlatformProvider } from "@/lib/types";
import { ConnectionStatusBadge, SandboxBadge } from "./PermissionStatus";

const TONE: Record<ExternalTranscriptStatus, "neutral" | "info" | "success" | "warning" | "danger"> = {
  unknown: "neutral",
  pending: "info",
  available: "info",
  imported: "success",
  not_available: "warning",
  permission_denied: "danger",
  failed: "danger",
};

/**
 * Meeting source selection: link a Teams/Zoom/Google Meet meeting to this
 * workspace, retrieve its authorized post-meeting transcript, and (only when the
 * capability is truly available) arm live transcription. File import stays
 * available independently.
 */
export function MeetingSourceSelector({
  meetingId,
  editable,
  platform,
  onImported,
}: {
  meetingId: string;
  editable: boolean;
  platform?: string;
  onImported: () => void;
}) {
  const source = useApi<ExternalSource | null>(`/meetings/${meetingId}/external-source`);
  const connections = useApi<ConnectionView[]>(editable ? "/integrations" : null);
  const [provider, setProvider] = useState<PlatformProvider | "">("");
  const [reference, setReference] = useState("");
  const [meetings, setMeetings] = useState<AvailableMeeting[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const job = useJob(jobId, (finished: Job) => {
    setJobId(null);
    if (finished.status === "failed" && finished.error_message) setError(finished.error_message);
    void source.reload();
    onImported();
  });

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (source.loading && !source.data) return <Spinner />;
  const ref = source.data;

  if (ref) {
    const capOf = (name: CapabilityName) => ref.capabilities.find((c) => c.capability === name);
    const fetchCap = capOf("post_meeting_transcript");
    const liveCap = capOf("live_transcript");
    const live = ref.live_session;
    const liveActive = live && ["waiting", "running"].includes(live.status);
    return (
      <div className="space-y-3 text-sm" data-testid="meeting-source" data-transcript-status={ref.transcript_status}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{t.source.linked}:</span>
          <span>{connections.data?.find((c) => c.provider === ref.provider)?.display_name ?? ref.provider}</span>
          <code className="text-xs">{ref.provider_meeting_id}</code>
          <ConnectionStatusBadge status={ref.connection_status} />
          {ref.sandbox && <SandboxBadge />}
          <Badge tone={TONE[ref.transcript_status]}>{t.source.status[ref.transcript_status]}</Badge>
        </div>
        {ref.status_message && <p className="text-xs text-muted">{ref.status_message}</p>}
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs sm:grid-cols-4">
          <dt className="text-muted">{t.source.attempts}</dt>
          <dd>{ref.fetch_attempts}</dd>
          <dt className="text-muted">{t.source.nextCheck}</dt>
          <dd>{formatDateTime(ref.next_check_at)}</dd>
        </dl>
        {job && <p className="text-xs text-muted">{t.jobStatus[job.status]}…</p>}
        {error && <Alert tone="danger">{error}</Alert>}
        {editable && (
          <div className="flex flex-wrap gap-2">
            {fetchCap?.status === "available" ? (
              <Button
                size="sm"
                variant="primary"
                loading={busy === "fetch" || !!jobId}
                data-testid="source-fetch"
                onClick={() => void run("fetch", async () => setJobId((await api.post<Job>(`/meetings/${meetingId}/external-source/fetch`)).id))}
              >
                {ref.transcript_status === "pending" || ref.transcript_status === "failed" ? t.source.retry : t.source.fetch}
              </Button>
            ) : (
              <Alert tone="warning">
                {t.source.fetchUnavailable} {fetchCap?.message}
              </Alert>
            )}
            {liveCap?.status === "available" ? (
              liveActive ? (
                <Button size="sm" loading={busy === "stop"} onClick={() => void run("stop", async () => { await api.post(`/meetings/${meetingId}/external-source/live/stop`); await source.reload(); })}>
                  {t.source.stopLive}
                </Button>
              ) : (
                <Button size="sm" loading={busy === "live"} onClick={() => void run("live", async () => { await api.post(`/meetings/${meetingId}/external-source/live/start`); await source.reload(); })}>
                  {t.source.startLive}
                </Button>
              )
            ) : null}
            {liveActive && (
              <Link href={`/meetings/${meetingId}/live`} className="self-center text-xs text-info underline">
                {t.source.openLive}
              </Link>
            )}
            <Button
              size="sm"
              variant="ghost"
              loading={busy === "unlink"}
              onClick={() => void run("unlink", async () => { await api.del(`/meetings/${meetingId}/external-source`); await source.reload(); })}
            >
              {t.source.unlink}
            </Button>
          </div>
        )}
        {liveCap && liveCap.status !== "available" && (
          <p className="text-xs text-muted">
            {t.source.liveUnavailable} {liveCap.message}
          </p>
        )}
      </div>
    );
  }

  if (!editable) return null;
  const usable = (connections.data ?? []).filter((c) => c.configured);
  const isUp = (c: ConnectionView) => ["connected", "connected_post_meeting_only"].includes(c.status);
  // Default: the meeting's own platform, else a connected platform, else the first configured one.
  const chosen =
    usable.find((c) => c.provider === provider) ?? usable.find((c) => c.provider === platform) ?? usable.find(isUp) ?? usable[0];
  const isConnected = chosen && isUp(chosen);

  return (
    <div className="space-y-3 text-sm" data-testid="meeting-source">
      {connections.data && usable.length === 0 && (
        <Alert tone="neutral">
          {t.source.notConnected} <Link href="/integrations" className="underline">{t.nav.integrations}</Link>
        </Alert>
      )}
      {chosen && (
        <>
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t.source.provider}>
              {(fid) => (
                <Select id={fid} value={chosen.provider} onChange={(e) => { setProvider(e.target.value as PlatformProvider); setMeetings(null); }} data-testid="source-provider">
                  {usable.map((c) => (
                    <option key={c.provider} value={c.provider}>
                      {c.display_name} — {t.integrations.status[c.status]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {chosen.sandbox && <SandboxBadge />}
          </div>
          {!isConnected ? (
            <Alert tone="warning">
              {t.source.notConnected} <Link href="/integrations" className="underline">{t.nav.integrations}</Link>
            </Alert>
          ) : (
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void run("link", async () => {
                  await api.post(`/meetings/${meetingId}/external-source`, { provider: chosen.provider, reference: reference.trim() });
                  setReference("");
                  await source.reload();
                });
              }}
            >
              <Field label={t.source.reference} hint={t.source.referenceHint[chosen.provider]} className="min-w-72 flex-1">
                {(fid) => <Input id={fid} value={reference} onChange={(e) => setReference(e.target.value)} required maxLength={2000} data-testid="source-reference" />}
              </Field>
              <Button type="submit" variant="primary" loading={busy === "link"} disabled={!reference.trim()} data-testid="source-link">
                {t.source.linkBtn}
              </Button>
              {chosen.capabilities.some((c) => c.capability === "list_meetings" && c.status === "available") && (
                <Button
                  type="button"
                  loading={busy === "list"}
                  onClick={() => void run("list", async () => setMeetings(await api.get<AvailableMeeting[]>(`/integrations/${chosen.provider}/meetings`)))}
                >
                  {t.source.loadMeetings}
                </Button>
              )}
            </form>
          )}
          {meetings && (
            <div>
              <p className="mb-1 text-xs font-medium">{t.source.pick}</p>
              {meetings.length === 0 ? (
                <p className="text-xs text-muted">{t.common.none}</p>
              ) : (
                <ul className="max-h-56 divide-y divide-line overflow-auto rounded border border-line">
                  {meetings.map((m) => (
                    <li key={m.provider_meeting_id}>
                      <button
                        type="button"
                        className="flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left hover:bg-surface-2"
                        onClick={() => setReference(m.join_url ?? m.provider_meeting_id)}
                      >
                        <span className="truncate">{m.title}</span>
                        <span className="text-xs whitespace-nowrap text-muted">
                          {formatDateTime(m.start)} {m.has_transcript ? `· ${t.source.hasTranscript}` : ""}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
    </div>
  );
}
