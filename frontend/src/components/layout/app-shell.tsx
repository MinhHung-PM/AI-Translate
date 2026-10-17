"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { BarChart3, ClipboardList, FolderKanban, History, LayoutDashboard, LogOut, PlusCircle,
  Mic, Plug, Settings, Shield } from "lucide-react";
import { Shuriken, Spinner, SwirlCloud, cn } from "@/components/ui";
import { t } from "@/lib/i18n";
import { useSession } from "@/lib/session";

const NAV = [
  { href: "/", label: t.nav.dashboard, icon: LayoutDashboard },
  { href: "/live", label: t.nav.liveTranslate, icon: Mic },
  { href: "/meetings/new", label: t.nav.newMeeting, icon: PlusCircle },
  { href: "/meetings", label: t.nav.history, icon: History },
  { href: "/actions", label: t.nav.actions, icon: ClipboardList },
  { href: "/projects", label: t.nav.projects, icon: FolderKanban },
  { href: "/usage", label: t.nav.usage, icon: BarChart3 },
  { href: "/integrations", label: t.nav.integrations, icon: Plug },
  { href: "/settings", label: t.nav.settings, icon: Settings },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  if (href === "/meetings") return pathname === "/meetings" || (pathname.startsWith("/meetings/") && pathname !== "/meetings/new");
  return pathname.startsWith(href);
}

export function AppShell({ children }: { children: ReactNode }) {
  const { session, loading, logout } = useSession();
  const pathname = usePathname();

  if (loading || !session) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label={t.common.loading} />
      </div>
    );
  }
  const items = session.user.role === "admin" ? [...NAV, { href: "/admin", label: t.nav.admin, icon: Shield }] : NAV;

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Bỏ qua điều hướng
      </a>
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r-4 border-brand-500 bg-navy-800 text-white md:flex">
        <div className="group flex items-center gap-2.5 border-b-2 border-white/10 px-4 py-4">
          <Shuriken className="size-9 text-brand-500 transition-transform duration-700 group-hover:rotate-180" />
          <div>
            <p className="text-base leading-tight font-black tracking-tight">{t.app.short}</p>
            <p className="text-[11px] font-semibold text-brand-100/80">AI Meeting Translator</p>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 p-2" aria-label="Main">
          {items.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(pathname, href) ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-semibold transition-colors",
                isActive(pathname, href)
                  ? "border-2 border-ink bg-brand-500 text-white shadow-[2px_2px_0_0_#0b1022]"
                  : "border-2 border-transparent text-white/80 hover:bg-white/10 hover:text-white",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          ))}
        </nav>
        <SwirlCloud className="mx-auto mb-1 h-8 w-24 text-navy-700" />
        <div className="border-t-2 border-white/10 p-3 text-xs">
          <p className="truncate font-medium" title={session.user.email}>
            {session.user.display_name}
          </p>
          <p className="text-white/60">{t.roles[session.user.role]}</p>
          {session.auth_mode === "dev" && <p className="mt-1 font-bold text-brand-500">DEV AUTH</p>}
          <button type="button" onClick={() => void logout()} className="mt-2 inline-flex items-center gap-1 text-white/60 hover:text-white">
            <LogOut className="size-3.5" aria-hidden /> {t.nav.logout}
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 overflow-x-auto border-b-4 border-brand-500 bg-navy-800 px-3 py-2 md:hidden">
          <Shuriken className="size-6 shrink-0 text-brand-500" />
          {items.map(({ href, label }) => (
            <Link key={href} href={href} className={cn("rounded-full px-2.5 py-1 text-xs font-semibold whitespace-nowrap text-white/80", isActive(pathname, href) && "bg-brand-500 text-white")}>
              {label}
            </Link>
          ))}
        </header>
        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-5 md:px-6">
          {children}
        </main>
      </div>
    </div>
  );
}
