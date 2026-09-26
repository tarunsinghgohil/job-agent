"use client";

import { useState } from "react";
import { Badge, StatusBadge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card, CardGrid } from "../../components/Card";
import { Input } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { Toggle } from "../../components/Toggle";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { formatDateTime, formatDuration } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import type { Agent, AgentRun } from "../../lib/types";

export function AutomationsView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const [cronDraft, setCronDraft] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState<string | null>(null);

  const agents = useResource<Agent[]>((signal) => api.get<Agent[]>("/api/v1/agents", undefined, signal));
  const runs = useResource<AgentRun[]>((signal) => api.get<AgentRun[]>("/api/v1/agents/runs", { limit: 100 }, signal));

  async function toggle(agent: Agent) {
    await run(`toggle-${agent.key}`, async () => {
      await api.put(`/api/v1/agents/${agent.key}`, { enabled: !agent.enabled });
      agents.reload();
    });
  }

  async function saveCron(agent: Agent) {
    const cron = cronDraft[agent.key];
    if (!cron) return;
    await run(`cron-${agent.key}`, async () => {
      await toast.withToast(() => api.put(`/api/v1/agents/${agent.key}`, { schedule_cron: cron }), "Schedule updated.");
      agents.reload();
    });
  }

  async function runNow(key: string) {
    await run(`run-${key}`, async () => {
      await toast.withToast(() => api.post(`/api/v1/agents/${key}/run`), "Run finished.", "Run failed");
      agents.reload();
      runs.reload();
    });
  }

  return (
    <>
      <PageHeader title="Automations" description="Every agent, its schedule, and its run history." />

      <AsyncBoundary
        loading={agents.loading}
        error={agents.error}
        data={agents.data}
        onRetry={agents.reload}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="No agents registered" />}
      >
        {(items) => (
          <CardGrid columns={2}>
            {items.map((agent) => (
              <Card
                key={agent.key}
                title={
                  <>
                    {agent.name} {!agent.enabled && <Badge tone="neutral">Disabled</Badge>}
                  </>
                }
                description={agent.description}
                actions={<Toggle checked={agent.enabled} onChange={() => void toggle(agent)} label="Enabled" />}
              >
                <dl className="def-list">
                  <dt>Last run</dt>
                  <dd>
                    {formatDateTime(agent.last_run_at)} <StatusBadge value={agent.last_status || "never"} />
                  </dd>
                  <dt>Next run</dt>
                  <dd>{formatDateTime(agent.next_run_at)}</dd>
                </dl>
                <div className="toolbar">
                  <Input
                    label="Cron"
                    value={cronDraft[agent.key] ?? agent.schedule_cron}
                    onChange={(e) => setCronDraft((c) => ({ ...c, [agent.key]: e.target.value }))}
                  />
                  <Button size="sm" loading={isPending(`cron-${agent.key}`)} onClick={() => void saveCron(agent)}>
                    Save
                  </Button>
                </div>
                <div className="button-row">
                  <Button loading={isPending(`run-${agent.key}`)} onClick={() => void runNow(agent.key)}>
                    Run now
                  </Button>
                  <Button variant="ghost" onClick={() => setExpanded(expanded === agent.key ? null : agent.key)}>
                    {expanded === agent.key ? "Hide history" : "Show history"}
                  </Button>
                </div>
                {expanded === agent.key && (
                  <ul className="list-rows">
                    {(runs.data ?? [])
                      .filter((r) => r.agent_key === agent.key)
                      .slice(0, 10)
                      .map((r) => (
                        <li className="list-row" key={r.id}>
                          <div className="list-row-main">
                            <strong>
                              <StatusBadge value={r.status} /> {r.trigger}
                            </strong>
                            <span>
                              {formatDateTime(r.created_at)} · {formatDuration(r.duration_ms)} · {r.items_succeeded}/
                              {r.items_processed} succeeded
                            </span>
                            {r.error && <span className="field-error">{r.error}</span>}
                          </div>
                        </li>
                      ))}
                    {(runs.data ?? []).filter((r) => r.agent_key === agent.key).length === 0 && (
                      <EmptyState title="No runs yet" />
                    )}
                  </ul>
                )}
              </Card>
            ))}
          </CardGrid>
        )}
      </AsyncBoundary>
    </>
  );
}
