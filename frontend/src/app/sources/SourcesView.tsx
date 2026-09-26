"use client";

import { useState } from "react";
import { Badge, StatusBadge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card, CardGrid } from "../../components/Card";
import { FieldRow, Input, Select } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { Toggle } from "../../components/Toggle";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { formatDateTime, titleize } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import type { DiscoverResult, JobSource, SourceAdapterInfo, TestResult } from "../../lib/types";

interface NewSourceDraft {
  name: string;
  adapter_type: string;
  config: Record<string, string>;
  credential: string;
}

export function SourcesView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const adapters = useResource<SourceAdapterInfo[]>((signal) => api.get<SourceAdapterInfo[]>("/api/v1/sources/adapters", undefined, signal));
  const sources = useResource<JobSource[]>((signal) => api.get<JobSource[]>("/api/v1/sources", undefined, signal));

  const [draft, setDraft] = useState<NewSourceDraft>({ name: "", adapter_type: "", config: {}, credential: "" });
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [syncResults, setSyncResults] = useState<Record<string, DiscoverResult>>({});

  const selectedAdapter = adapters.data?.find((a) => a.adapter_type === draft.adapter_type);

  async function createSource() {
    if (!draft.name.trim() || !draft.adapter_type) {
      toast.error("Name and adapter type are required.");
      return;
    }
    await run("create", async () => {
      const ok = await toast.withToast(
        () =>
          api.post("/api/v1/sources", {
            name: draft.name,
            adapter_type: draft.adapter_type,
            config: draft.config,
            credential: draft.credential || null,
            enabled: true,
            priority: 100,
          }),
        "Source added.",
        "Could not add the source",
      );
      if (ok !== undefined) {
        setDraft({ name: "", adapter_type: "", config: {}, credential: "" });
        sources.reload();
      }
    });
  }

  async function toggleEnabled(source: JobSource) {
    await run(`toggle-${source.id}`, async () => {
      await api.put(`/api/v1/sources/${source.id}`, { ...source, enabled: !source.enabled });
      sources.reload();
    });
  }

  async function testSource(id: string) {
    await run(`test-${id}`, async () => {
      const result = await toast.withToast(() => api.post<TestResult>(`/api/v1/sources/${id}/test`), "Test complete.");
      if (result) setTestResults((current) => ({ ...current, [id]: result }));
      sources.reload();
    });
  }

  async function syncSource(id: string) {
    await run(`sync-${id}`, async () => {
      const result = await toast.withToast(() => api.post<DiscoverResult>(`/api/v1/sources/${id}/sync`), "Sync complete.");
      if (result) setSyncResults((current) => ({ ...current, [id]: result }));
      sources.reload();
    });
  }

  async function remove(id: string) {
    await run(`del-${id}`, async () => {
      await toast.withToast(() => api.del(`/api/v1/sources/${id}`), "Source removed.");
      sources.reload();
    });
  }

  return (
    <>
      <PageHeader title="Job sources" description="Adding a provider is configuration, never a code change." />

      <Card title="Add a source">
        <FieldRow>
          <Input label="Name" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
          <Select
            label="Adapter"
            placeholder="Choose an adapter"
            options={(adapters.data ?? []).map((a) => ({ value: a.adapter_type, label: a.display_name }))}
            value={draft.adapter_type}
            onChange={(e) => setDraft((d) => ({ ...d, adapter_type: e.target.value, config: {} }))}
          />
        </FieldRow>
        {selectedAdapter && (
          <CardGrid columns={2}>
            {selectedAdapter.config_schema.map((field) => (
              <Input
                key={field.key}
                label={field.label ?? field.key}
                hint={field.help}
                placeholder={field.placeholder}
                required={field.required}
                value={draft.config[field.key] ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, config: { ...d.config, [field.key]: e.target.value } }))}
              />
            ))}
          </CardGrid>
        )}
        {selectedAdapter?.requires_credential && (
          <Input
            label="Credential"
            type="password"
            hint="Stored encrypted. Never shown again after saving."
            value={draft.credential}
            onChange={(e) => setDraft((d) => ({ ...d, credential: e.target.value }))}
          />
        )}
        <Button variant="primary" loading={isPending("create")} onClick={() => void createSource()}>
          Add source
        </Button>
      </Card>

      <AsyncBoundary
        loading={sources.loading}
        error={sources.error}
        data={sources.data}
        onRetry={sources.reload}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="No sources configured" description="Add one above so the agent has somewhere to look." />}
      >
        {(items) => (
          <CardGrid columns={1}>
            {items.map((source) => (
              <Card
                key={source.id}
                title={
                  <>
                    {source.name} <StatusBadge value={source.health} /> {!source.enabled && <Badge tone="neutral">Disabled</Badge>}
                  </>
                }
                description={`${titleize(source.adapter_type)} · last success ${formatDateTime(source.last_success_at)}`}
                actions={
                  <>
                    <Toggle checked={source.enabled} onChange={() => void toggleEnabled(source)} label="Enabled" />
                    <Button size="sm" loading={isPending(`test-${source.id}`)} onClick={() => void testSource(source.id)}>
                      Test
                    </Button>
                    <Button size="sm" variant="primary" loading={isPending(`sync-${source.id}`)} onClick={() => void syncSource(source.id)}>
                      Sync now
                    </Button>
                    <Button size="sm" variant="danger" loading={isPending(`del-${source.id}`)} onClick={() => void remove(source.id)}>
                      Remove
                    </Button>
                  </>
                }
              >
                {source.last_error && <p className="inline-error">{source.last_error}</p>}
                {testResults[source.id] && (
                  <p className={testResults[source.id].ok ? "muted" : "inline-error"}>{testResults[source.id].message}</p>
                )}
                {syncResults[source.id] && (
                  <p className="muted">
                    Created {syncResults[source.id].created}, updated {syncResults[source.id].updated}, skipped{" "}
                    {syncResults[source.id].skipped}
                  </p>
                )}
              </Card>
            ))}
          </CardGrid>
        )}
      </AsyncBoundary>
    </>
  );
}
