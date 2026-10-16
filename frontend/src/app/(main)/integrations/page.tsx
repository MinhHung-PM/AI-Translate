"use client";

import { useSearchParams } from "next/navigation";
import { Alert, PageHeader, Spinner } from "@/components/ui";
import { PlatformConnectionCard } from "@/components/integrations/PlatformConnectionCard";
import { errorMessage } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { ConnectionView } from "@/lib/types";

export default function IntegrationsPage() {
  const params = useSearchParams();
  const { data, error, setData } = useApi<ConnectionView[]>("/integrations");
  const result = params.get("result");
  const provider = params.get("provider");
  const category = params.get("category");
  const returned = data?.find((c) => c.provider === provider);

  return (
    <>
      <PageHeader title={t.integrations.title} subtitle={t.integrations.subtitle} />
      {result === "connected" && (
        <Alert tone="success" className="mb-3" title={returned?.display_name}>
          {t.integrations.connectedOk}
        </Alert>
      )}
      {result === "error" && (
        <Alert tone="danger" className="mb-3" title={`${t.integrations.connectFailed}${returned ? ` — ${returned.display_name}` : ""}`}>
          {returned?.last_error_message ?? category}
          {category && <span className="ml-1 font-mono text-xs">({category})</span>}
        </Alert>
      )}
      {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      {!data ? (
        <Spinner label={t.common.loading} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3" data-testid="integrations">
          {data.map((v) => (
            <PlatformConnectionCard key={v.provider} view={v} onChanged={(nv) => setData(data.map((c) => (c.provider === nv.provider ? nv : c)))} />
          ))}
        </div>
      )}
    </>
  );
}
