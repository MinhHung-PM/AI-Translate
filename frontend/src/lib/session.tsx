"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, setCsrfToken } from "./api";
import type { SessionInfo } from "./types";

interface SessionContextValue {
  session: SessionInfo | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  setSession: (s: SessionInfo) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const setSession = useCallback((s: SessionInfo) => {
    setCsrfToken(s.csrf_token);
    setSessionState(s);
  }, []);

  const refresh = useCallback(
    (): Promise<void> =>
      api.get<SessionInfo>("/auth/me").then(
        (s) => {
          setSession(s);
          setLoading(false);
        },
        (err: unknown) => {
          setSessionState(null);
          setLoading(false);
          if (err instanceof ApiError && err.status === 401 && pathname !== "/login") router.replace("/login");
        },
      ),
    [pathname, router, setSession],
  );

  // Resolve the session once on first mount; navigation keeps it.
  const initialRefresh = useRef(refresh);
  useEffect(() => {
    void initialRefresh.current();
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setCsrfToken("");
      setSessionState(null);
      router.replace("/login");
    }
  }, [router]);

  return <SessionContext.Provider value={{ session, loading, refresh, logout, setSession }}>{children}</SessionContext.Provider>;
}

/** A server feature flag from /auth/me (false while the session loads). */
export function useFeature(name: string): boolean {
  return !!useSession().session?.features[name];
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
