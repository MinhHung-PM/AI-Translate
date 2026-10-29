"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { BarChart3, ClipboardCheck, FolderKanban, LayoutDashboard, ListTodo, LogOut, Plug, Settings, Shield, Users } from "lucide-react";
import { Spinner, cn } from "@/components/ui";
import { t } from "@/lib/i18n";
import { setPrefs, useFocusMode, usePrefs } from "@/lib/prefs";
import { useSession } from "@/lib/session";

type NavId = "home" | "meetings" | "memos" | "actions" | "projects" | "usage" | "integrations" | "settings" | "admin";
interface NavItem {
  id: NavId;
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
}

// Main flow first (live → minutes → tasks), management below. "Cuộc họp" merges history + new meeting.
const MAIN: NavItem[] = [
  { id: "home", href: "/", label: t.nav.dashboard, icon: LayoutDashboard },
  { id: "meetings", href: "/meetings", label: t.nav.meetings, icon: Users },
  { id: "memos", href: "/meetings?memo=in_review", label: t.nav.memos, icon: ClipboardCheck },
  { id: "actions", href: "/actions", label: t.nav.actions, icon: ListTodo },
];
const MANAGE: NavItem[] = [
  { id: "projects", href: "/projects", label: t.nav.projects, icon: FolderKanban },
  { id: "usage", href: "/usage", label: t.nav.usage, icon: BarChart3 },
  { id: "integrations", href: "/integrations", label: t.nav.integrations, icon: Plug },
  { id: "settings", href: "/settings", label: t.nav.settings, icon: Settings },
];

function activeId(pathname: string, memoFilter: boolean): NavId | null {
  if (pathname === "/") return "home";
  if (pathname === "/live") return null; // the pinned live button marks itself
  if (/^\/meetings\/[^/]+\/memo/.test(pathname) || (pathname === "/meetings" && memoFilter)) return "memos";
  if (pathname.startsWith("/meetings")) return "meetings";
  for (const id of ["actions", "projects", "usage", "integrations", "settings", "admin"] as const) {
    if (pathname.startsWith(`/${id}`)) return id;
  }
  return null;
}

export function AppShell({ children }: { children: ReactNode }) {
  const { session, loading, logout } = useSession();
  const pathname = usePathname();
  const memoFilter = useSearchParams().has("memo");
  const focus = useFocusMode();
  const { theme, showFred } = usePrefs();

  if (loading || !session) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label={t.common.loading} />
      </div>
    );
  }
  // Shared team site (no sign-in): AI keys are managed on the server, so no AI settings / sign-out.
  const shared = !!session.features.shared_mode;
  // No meeting platform configured on the server: the integrations page could not do anything.
  const hidden = new Set<NavId>([...(shared ? ["settings" as const] : []), ...(session.features.integrations ? [] : ["integrations" as const])]);
  const manage = [...MANAGE.filter((n) => !hidden.has(n.id)), ...(session.user.role === "admin" ? [{ id: "admin" as const, href: "/admin", label: t.nav.admin, icon: Shield }] : [])];
  const current = activeId(pathname, memoFilter);
  const liveCurrent = pathname === "/live" || /^\/meetings\/[^/]+\/live/.test(pathname);
  // The live screen runs edge to edge; every other page sits in the padded content column.
  const fullBleed = /^\/meetings\/[^/]+\/live/.test(pathname);

  const link = (n: NavItem) => (
    <Link
      key={n.id}
      href={n.href}
      aria-current={current === n.id ? "page" : undefined}
      className={cn(
        "flex shrink-0 items-center gap-2.5 rounded-[10px] px-3 py-2 text-sm whitespace-nowrap transition-colors",
        current === n.id ? "bg-surface-2 font-semibold text-ink" : "font-medium text-muted hover:text-ink",
      )}
    >
      <n.icon className="size-4 shrink-0" aria-hidden />
      {n.label}
    </Link>
  );

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Bỏ qua điều hướng
      </a>
      {!focus && (
        <nav
          aria-label={t.nav.main}
          className="sticky top-0 z-10 flex shrink-0 items-center gap-1 overflow-x-auto border-b border-line bg-nav px-2.5 py-2 lg:fixed lg:inset-y-0 lg:left-0 lg:h-screen lg:w-[236px] lg:flex-col lg:items-stretch lg:gap-0.5 lg:overflow-y-auto lg:border-r lg:border-b-0 lg:px-3 lg:py-[18px]"
        >
          <Link href="/" className="flex shrink-0 items-center gap-2.5 px-2 lg:pb-4">
            <span className="size-[34px] shrink-0 rounded-full bg-surface-2 bg-[url(/fred/wave.webp)] bg-[length:160%] bg-[position:center_18%] bg-no-repeat" aria-hidden />
            <span className="hidden flex-col lg:flex">
              <span className="font-display text-[15px] font-semibold">{t.app.short}</span>
              <span className="font-mono text-[10px] tracking-wider text-muted">{t.nav.tagline}</span>
            </span>
          </Link>
          <Link
            href="/live"
            aria-current={liveCurrent ? "page" : undefined}
            className="mx-1 flex shrink-0 items-center justify-center gap-2.5 rounded-xl bg-accent px-3.5 py-2 text-sm font-bold whitespace-nowrap text-accent-ink lg:mb-3.5 lg:py-3"
          >
            <span className="size-2 rounded-full bg-[#d93a2b]" aria-hidden />
            {t.nav.liveTranslate}
          </Link>
          <span className="eyebrow hidden px-3 pt-3.5 pb-1.5 text-subtle lg:block">{t.nav.mainFlow}</span>
          {MAIN.map(link)}
          <span className="eyebrow hidden px-3 pt-3.5 pb-1.5 text-subtle lg:block">{t.nav.manage}</span>
          {manage.map(link)}

          <div className="mt-auto hidden flex-col gap-2.5 border-t border-line p-3 lg:flex">
            <div className="flex rounded-full border border-line p-0.5 text-xs" role="radiogroup" aria-label={t.nav.theme}>
              {(["dark", "light"] as const).map((th) => (
                <button
                  key={th}
                  type="button"
                  role="radio"
                  aria-checked={theme === th}
                  onClick={() => setPrefs({ theme: th })}
                  className={cn("flex-1 rounded-full py-1.5", theme === th ? "bg-ink text-bg" : "text-muted hover:text-ink")}
                >
                  {th === "dark" ? t.nav.dark : t.nav.light}
                </button>
              ))}
            </div>
            <label className="flex cursor-pointer items-center justify-between gap-2 text-xs text-muted">
              {t.nav.showFred}
              <input type="checkbox" className="size-4 accent-accent" checked={showFred} onChange={(e) => setPrefs({ showFred: e.target.checked })} />
            </label>
            {shared ? (
              <span className="text-xs text-muted">{t.nav.sharedSite}</span>
            ) : (
              <div className="text-xs">
                <p className="truncate font-medium" title={session.user.email}>
                  {session.user.display_name}
                </p>
                <p className="text-muted">{t.roles[session.user.role]}</p>
                <button type="button" onClick={() => void logout()} className="mt-1.5 inline-flex items-center gap-1 text-muted hover:text-ink">
                  <LogOut className="size-3.5" aria-hidden /> {t.nav.logout}
                </button>
              </div>
            )}
            {session.auth_mode === "dev" && <span className="font-mono text-[10px] font-medium text-warning">DEV AUTH</span>}
          </div>
        </nav>
      )}
      <main id="main" className={cn("flex min-w-0 flex-1 flex-col", !focus && "lg:ml-[236px]")}>
        {fullBleed ? children : <div className="w-full max-w-[1360px] flex-1 px-[clamp(18px,3vw,36px)] py-[clamp(18px,3vw,32px)]">{children}</div>}
      </main>
    </div>
  );
}
