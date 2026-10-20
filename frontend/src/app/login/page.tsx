"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Button, Card, Field, Fred, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import type { GlobalRole, SessionInfo } from "@/lib/types";

interface DevUser {
  email: string;
  display_name: string;
  role: GlobalRole;
}

export default function LoginPage() {
  const router = useRouter();
  const { setSession } = useSession();
  const [devUsers, setDevUsers] = useState<DevUser[] | null>(null);
  const [mode, setMode] = useState<"loading" | "dev" | "oidc">("loading");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Shared team site: /auth/me signs the browser in by itself — go straight to the app.
    api
      .get<SessionInfo>("/auth/me")
      .then((s) => {
        setSession(s);
        router.replace("/");
      })
      .catch(() => undefined);
    api
      .get<DevUser[]>("/auth/dev/users")
      .then((users) => {
        setDevUsers(users);
        setEmail(users.find((u) => u.role === "project_manager")?.email ?? users[0]?.email ?? "");
        setMode("dev");
      })
      .catch((err) => setMode(err instanceof ApiError && err.status === 404 ? "oidc" : "oidc"));
  }, [router, setSession]);

  async function devLogin() {
    setBusy(true);
    setError(null);
    try {
      const session = await api.post<SessionInfo>("/auth/dev/login", { email });
      setSession(session);
      router.replace("/");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="mb-5 flex items-center gap-3">
          <Fred pose="wave" className="h-24 w-auto" priority />
          <div>
            <h1 className="font-display text-2xl leading-tight font-semibold text-ink">{t.app.short}</h1>
            <p className="text-sm text-muted">{t.login.subtitle}</p>
          </div>
        </div>
        <Card title={t.login.title}>
          {mode === "dev" && devUsers && (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                void devLogin();
              }}
            >
              <Alert tone="warning">{t.login.devMode}</Alert>
              <Field label={t.login.pickUser}>
                {(id) => (
                  <Select id={id} value={email} onChange={(e) => setEmail(e.target.value)} data-testid="dev-user">
                    {devUsers.map((u) => (
                      <option key={u.email} value={u.email}>
                        {u.display_name} — {t.roles[u.role]} ({u.email})
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              {error && <Alert tone="danger">{error}</Alert>}
              <Button type="submit" variant="primary" loading={busy} className="w-full">
                {t.login.signIn}
              </Button>
            </form>
          )}
          {mode === "oidc" && (
            <a href="/api/v1/auth/oidc/login" className="inline-flex h-10 w-full items-center justify-center rounded-full bg-accent text-sm font-bold text-accent-ink hover:brightness-105">
              {t.login.sso}
            </a>
          )}
          {mode === "loading" && <p className="text-sm text-muted">{t.common.loading}</p>}
        </Card>
      </div>
    </main>
  );
}
