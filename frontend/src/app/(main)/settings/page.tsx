"use client";

import { useMemo, useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, Field, Input, PageHeader, Select, Spinner, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import type { ProviderConfig, ProviderSettings } from "@/lib/types";

const CUSTOM = "__custom__";

export default function SettingsPage() {
  const settings = useApi<ProviderSettings>("/providers");
  const configs = useApi<ProviderConfig[]>("/providers/configs");
  const [selected, setSelected] = useState("");
  // Per-provider edits; when a field is undefined the saved configuration (or catalog default) is shown.
  const [edits, setEdits] = useState<{ model?: string; customModel?: string; baseUrl?: string }>({});
  // The API key exists only in this component's state until submitted; it is
  // never written to localStorage/sessionStorage, URLs or logs, and is cleared
  // immediately after saving.
  const [apiKey, setApiKey] = useState("");
  const [remember, setRemember] = useState(false);
  const [makeDefault, setMakeDefault] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "danger" | "info"; text: string } | null>(null);

  const provider = selected || configs.data?.find((c) => c.is_default)?.provider || settings.data?.providers[0]?.key || "";
  const info = useMemo(() => settings.data?.providers.find((p) => p.key === provider), [settings.data, provider]);
  const infoSpeechOnly = !!info && speechOnly(info.capabilities);
  const existing = configs.data?.find((c) => c.provider === provider);

  const savedModel = existing?.model;
  const defaultModel =
    savedModel && info?.models.some((m) => m.id === savedModel)
      ? savedModel
      : savedModel && info?.allow_custom_model
        ? CUSTOM
        : (info?.models[0]?.id ?? (info?.allow_custom_model ? CUSTOM : ""));
  const model = edits.model ?? defaultModel;
  const customModel = edits.customModel ?? (defaultModel === CUSTOM ? (savedModel ?? "") : "");
  const baseUrl = edits.baseUrl ?? existing?.base_url ?? "";
  const setModel = (v: string) => setEdits((e) => ({ ...e, model: v }));
  const setCustomModel = (v: string) => setEdits((e) => ({ ...e, customModel: v }));
  const setBaseUrl = (v: string) => setEdits((e) => ({ ...e, baseUrl: v }));
  const setProvider = (v: string) => {
    setSelected(v);
    setEdits({});
    setApiKey("");
  };

  async function save() {
    if (!info) return;
    setBusy("save");
    setMessage(null);
    try {
      await api.put<ProviderConfig>("/providers/configs", {
        provider,
        model: model === CUSTOM ? customModel : model,
        base_url: info.allow_custom_base_url ? baseUrl || null : null,
        api_key: apiKey ? apiKey : null,
        remember,
        make_default: makeDefault && !infoSpeechOnly,
      });
      setApiKey("");
      setEdits({});
      setMessage({ tone: "success", text: t.settings.saved });
      await configs.reload();
    } catch (err) {
      setMessage({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  }

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setMessage(null);
    try {
      await fn();
      await configs.reload();
    } catch (err) {
      setMessage({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  }

  if (!settings.data || !configs.data) return <Spinner label={t.common.loading} />;
  const s = settings.data;

  return (
    <>
      <PageHeader title={t.settings.title} />
      <div className="mb-4 space-y-2">
        <Alert tone="info">{t.settings.dataNotice}</Alert>
        {!s.secret_storage_available && <Alert tone="warning">{t.settings.noSecretStorage}</Alert>}
      </div>
      {message && <Alert tone={message.tone} className="mb-3">{message.text}</Alert>}

      <div className="grid gap-4 xl:grid-cols-5">
        <Card title={t.settings.provider} className="xl:col-span-2">
          <div className="space-y-3">
            <Field label={t.settings.provider}>
              {(id) => (
                <Select id={id} value={provider} onChange={(e) => setProvider(e.target.value)} data-testid="provider-select">
                  {s.providers.map((p) => (
                    <option key={p.key} value={p.key}>
                      {p.display_name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {info?.dev_only && <Alert tone="warning">{t.settings.mockNotice}</Alert>}
            {info && (
              <>
                <Field label={t.settings.model}>
                  {(id) => (
                    <Select id={id} value={model} onChange={(e) => setModel(e.target.value)}>
                      {info.models.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.label ?? m.id}
                        </option>
                      ))}
                      {info.allow_custom_model && <option value={CUSTOM}>{t.settings.customModel}…</option>}
                    </Select>
                  )}
                </Field>
                {model === CUSTOM && (
                  <Field label={t.settings.customModel}>{(id) => <Input id={id} value={customModel} onChange={(e) => setCustomModel(e.target.value)} />}</Field>
                )}
                {info.allow_custom_base_url && (
                  <Field label={t.settings.baseUrl}>{(id) => <Input id={id} type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" />}</Field>
                )}
                {info.requires_api_key && (
                  <>
                    <Field label={t.settings.apiKey} hint={existing?.key_hint ? `${t.settings.keyStatus}: ${t.settings.keyStorage[existing.key_storage]} ${existing.key_hint}` : undefined}>
                      {(id) => (
                        <Input
                          id={id}
                          type="password"
                          autoComplete="off"
                          spellCheck={false}
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          placeholder={t.settings.apiKeyPlaceholder}
                          disabled={!s.secret_storage_available}
                        />
                      )}
                    </Field>
                    <Checkbox label={t.settings.remember} checked={remember} disabled={!s.remember_key_supported} onChange={(e) => setRemember(e.target.checked)} />
                    <p className="text-xs text-muted">{s.remember_key_supported ? t.settings.sessionOnly : t.settings.rememberDisabled}</p>
                  </>
                )}
                {infoSpeechOnly ? (
                  <Alert tone="info">{t.settings.speechOnly}</Alert>
                ) : (
                  <Checkbox label={t.settings.makeDefault} checked={makeDefault} onChange={(e) => setMakeDefault(e.target.checked)} />
                )}
                <div>
                  <p className="mb-1 text-xs font-medium text-gray-700">{t.settings.capabilities}</p>
                  <div className="flex flex-wrap gap-1">
                    {info.capabilities.map((c) => (
                      <Badge key={c} tone="brand">
                        {c}
                      </Badge>
                    ))}
                  </div>
                </div>
                {info.models.some((m) => m.input_per_1m !== null) && (
                  <p className="text-xs text-muted">
                    {t.settings.pricing}:{" "}
                    {info.models.map((m) => `${m.id} ${m.input_per_1m ?? "?"}/${m.output_per_1m ?? "?"}`).join(" · ")}
                  </p>
                )}
                <Button variant="primary" onClick={() => void save()} loading={busy === "save"} disabled={model === CUSTOM && !customModel} data-testid="provider-save">
                  {t.common.save}
                </Button>
              </>
            )}
          </div>
        </Card>

        <Card title={t.settings.configured} className="xl:col-span-3" bodyClassName="p-0">
          <Table>
            <thead>
              <tr>
                <th>{t.settings.provider}</th>
                <th>{t.settings.model}</th>
                <th>{t.settings.keyStatus}</th>
                <th>{t.settings.test}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {configs.data.map((c) => {
                const p = s.providers.find((x) => x.key === c.provider);
                return (
                  <tr key={c.id}>
                    <td>
                      {p?.display_name ?? c.provider} {c.is_default && <Badge tone="brand">{t.settings.default}</Badge>}
                    </td>
                    <td className="font-mono text-xs">{c.model}</td>
                    <td className="text-xs">
                      {p?.requires_api_key ? (
                        <>
                          <Badge tone={c.has_usable_key ? "success" : "warning"}>{t.settings.keyStorage[c.key_storage]}</Badge> {c.key_hint}
                          {c.key_storage === "session" && !c.has_usable_key && <p className="text-amber-700">{t.settings.keyMissingInSession}</p>}
                        </>
                      ) : (
                        <span className="text-muted">{t.common.none}</span>
                      )}
                    </td>
                    <td className="text-xs">
                      {c.last_test_ok === null ? (
                        <span className="text-muted">{t.common.none}</span>
                      ) : (
                        <>
                          <Badge tone={c.last_test_ok ? "success" : "danger"}>{c.last_test_ok ? "OK" : "FAIL"}</Badge>
                          <p className="text-muted">{c.last_test_message}</p>
                          <p className="text-muted">{formatDateTime(c.last_tested_at)}</p>
                        </>
                      )}
                    </td>
                    <td>
                      <div className="flex flex-wrap justify-end gap-1">
                        <Button size="sm" onClick={() => void act(`test-${c.id}`, () => api.post(`/providers/configs/${c.id}/test`))} loading={busy === `test-${c.id}`}>
                          {t.settings.test}
                        </Button>
                        {!c.is_default && !(p && speechOnly(p.capabilities)) && (
                          <Button size="sm" onClick={() => void act(`def-${c.id}`, () => api.post(`/providers/configs/${c.id}/default`))}>
                            {t.settings.makeDefault}
                          </Button>
                        )}
                        {c.key_storage !== "none" && (
                          <Button size="sm" variant="danger" onClick={() => void act(`key-${c.id}`, () => api.del(`/providers/configs/${c.id}/key`))}>
                            {t.settings.removeKey}
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" onClick={() => void act(`del-${c.id}`, () => api.del(`/providers/configs/${c.id}`))}>
                          {t.settings.removeConfig}
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </Card>
      </div>
    </>
  );
}

/** Speech-recognition-only providers (Soniox) never translate or write memos, so they cannot be the default. */
function speechOnly(capabilities: string[]): boolean {
  return !capabilities.includes("translation") && !capabilities.includes("memo_generation");
}
