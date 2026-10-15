import { Suspense, type ReactNode } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { Spinner } from "@/components/ui";

export default function MainLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell>
      <Suspense fallback={<Spinner />}>{children}</Suspense>
    </AppShell>
  );
}
