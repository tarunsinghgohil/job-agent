"use client";

import { useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card, CardGrid } from "../../components/Card";
import { Input } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { AsyncBoundary } from "../../components/States";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import type { Integration, TestResult } from "../../lib/types";

export function IntegrationsView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const integrations = useResource<Integration[]>((signal) => api.get<Integration[]>("/api/v1/integrations", undefined, signal));
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});

  async function save(key: string) {
    const value = draft[key]?.trim();
    if (!value) {
      toast.error("Enter a value first.");
      return;
    }
    await run(`save-${key}`, async () => {
      await toast.withToast(() => api.put(`/api/v1/integrations/${key}`, { value }), "Credential saved.", "Could not save");
      setDraft((d) => ({ ...d, [key]: "" }));
      integrations.reload();
    });
  }

  async function test(key: string) {
    await run(`test-${key}`, async () => {
      const result = await toast.withToast(() => api.post<TestResult>(`/api/v1/integrations/${key}/test`), "Test complete.");
      if (result) setTestResults((current) => ({ ...current, [key]: result }));
      integrations.reload();
    });
  }

  async function disconnect(key: string) {
    await run(`del-${key}`, async () => {
      await toast.withToast(() => api.del(`/api/v1/integrations/${key}`), "Disconnected.");
      integrations.reload();
    });
  }

  return (
    <>
      <PageHeader title="Integrations" description="Credentials are encrypted at rest and never shown in plain text again." />

      <AsyncBoundary loading={integrations.loading} error={integrations.error} data={integrations.data} onRetry={integrations.reload}>
        {(items) => (
          <CardGrid columns={2}>
            {items.map((integration) => (
              <Card
                key={integration.key}
                title={
                  <>
                    {integration.label}{" "}
                    {integration.connected ? <Badge tone="success">Connected</Badge> : <Badge tone="neutral">Not connected</Badge>}
                  </>
                }
                description={integration.source === "environment" ? "Set via environment variable" : undefined}
              >
                {integration.connected && (
                  <p className="mono">
                    {integration.masked_value}
                    {integration.rotated_at && <span className="muted"> · rotated {formatDateTime(integration.rotated_at)}</span>}
                  </p>
                )}
                {integration.last_test_ok !== null && (
                  <p className={integration.last_test_ok ? "muted" : "inline-error"}>
                    Last test {formatDateTime(integration.last_tested_at)}: {integration.last_test_ok ? "OK" : integration.last_test_error}
                  </p>
                )}
                {testResults[integration.key] && (
                  <p className={testResults[integration.key].ok ? "muted" : "inline-error"}>{testResults[integration.key].message}</p>
                )}
                <div className="toolbar">
                  <Input
                    type="password"
                    placeholder={integration.connected ? "Rotate: enter a new value" : "Enter credential"}
                    value={draft[integration.key] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [integration.key]: e.target.value }))}
                  />
                  <Button loading={isPending(`save-${integration.key}`)} onClick={() => void save(integration.key)}>
                    {integration.connected ? "Rotate" : "Connect"}
                  </Button>
                </div>
                <div className="button-row">
                  {integration.connected && (
                    <>
                      <Button size="sm" loading={isPending(`test-${integration.key}`)} onClick={() => void test(integration.key)}>
                        Test
                      </Button>
                      {integration.source === "database" && (
                        <Button size="sm" variant="danger" loading={isPending(`del-${integration.key}`)} onClick={() => void disconnect(integration.key)}>
                          Disconnect
                        </Button>
                      )}
                    </>
                  )}
                </div>
              </Card>
            ))}
          </CardGrid>
        )}
      </AsyncBoundary>
    </>
  );
}
