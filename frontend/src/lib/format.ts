import { ApiError } from "./api";
import { t } from "./i18n";

export function formatDateTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return t.common.none;
  try {
    return new Intl.DateTimeFormat("vi-VN", {
      dateStyle: "short",
      timeStyle: "short",
      timeZone: timeZone || undefined,
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return t.common.none;
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  const s = Math.floor(ms / 1000);
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return hh ? `${pad(hh)}:${pad(mm)}:${pad(ss)}` : `${pad(mm)}:${pad(ss)}`;
}

export function formatUsd(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  return `$${n.toFixed(n < 1 ? 4 : 2)}`;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const known = (t.errors as Record<string, string>)[err.code];
    if (err.status === 0) return t.common.networkError;
    if (!known) return err.message || t.common.errorGeneric;
    return err.message && err.message !== known ? `${known} (${err.message})` : known;
  }
  return t.common.errorGeneric;
}

/** datetime-local value (YYYY-MM-DDTHH:mm) interpreted in an IANA timezone -> ISO string with offset. */
export function zonedLocalToIso(local: string, timeZone: string): string {
  const [datePart, timePart = "00:00"] = local.split("T");
  const [y, mo, d] = datePart.split("-").map(Number);
  const [h, mi] = timePart.split(":").map(Number);
  const guess = Date.UTC(y, mo - 1, d, h, mi);
  const offset = tzOffsetMinutes(new Date(guess), timeZone);
  return new Date(guess - offset * 60_000).toISOString();
}

function tzOffsetMinutes(date: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"));
  return Math.round((asUtc - date.getTime()) / 60_000);
}

/** Live interpretation can return a translation whose source transcript never arrived: the
 * server stores the translation as the text then, and the UI must not present it as the original. */
export function originalMissing(e: { source_metadata?: Record<string, unknown> | null }): boolean {
  return e.source_metadata?.original_missing === true;
}
