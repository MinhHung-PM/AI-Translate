"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Button, Card, Field, Select } from "@/components/ui";
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
    api
      .get<DevUser[]>("/auth/dev/users")
      .then((users) => {
        setDevUsers(users);
        setEmail(users.find((u) => u.role === "project_manager")?.email ?? users[0]?.email ?? "");
        setMode("dev");
      })
      .catch((err) => setMode(err instanceof ApiError && err.status === 404 ? "oidc" : "oidc"));
  }, []);

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
        <h1 className="mb-1 text-lg font-semibold text-brand-700">{t.app.name}</h1>
        <p className="mb-4 text-sm text-muted">{t.login.subtitle}</p>
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
            <a href="/api/v1/auth/oidc/login" className="inline-flex h-9 w-full items-center justify-center rounded-md bg-brand-600 text-sm font-medium text-white hover:bg-brand-700">
              {t.login.sso}
            </a>
          )}
          {mode === "loading" && <p className="text-sm text-muted">{t.common.loading}</p>}
        </Card>
      </div>
    </main>
  );
}
