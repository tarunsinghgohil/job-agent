"use client";

import Link from "next/link";
import { Button } from "../components/Button";
import { Card, CardGrid } from "../components/Card";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/Badge";
import { StatGrid, StatTile, UsageMeter } from "../components/StatTile";
import { AsyncBoundary, EmptyState } from "../components/States";
import { useToast } from "../components/Toast";
import { api } from "../lib/api";
import { formatDateTime, formatUsd, relativeTime, titleize } from "../lib/format";
import { useResource, usePending } from "../lib/hooks";
import type { Dashboard, FollowUp } from "../lib/types";

/** Count keys that map onto a filtered list view. */
const COUNT_LINKS: Record<string, string> = {
  new_jobs: "/jobs?status=new",
  high_match: "/jobs?decision=HIGH_PRIORITY",
  review: "/jobs?decision=REVIEW",
  rejected: "/jobs?decision=REJECT",
  application_ready: "/applications?status=prepared",
  pending_approval: "/applications?status=pending_review",
  submitted: "/applications?status=submitted",
  interviews: "/applications?status=interview",
  offers: "/applications?status=offer",
  followups_due: "/applications",
};

const COUNT_TONES: Record<string, "neutral" | "success" | "warning" | "danger" | "info"> = {
  high_match: "success",
  offers: "success",
  review: "warning",
  pending_approval: "warning",
  followups_due: "warning",
  rejected: "danger",
  interviews: "info",
  submitted: "info",
};

export function OverviewView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const dashboard = useResource<Dashboard>((signal) => api.get<Dashboard>("/api/v1/dashboard", undefined, signal));
  const followups = useResource<FollowUp[]>((signal) =>
    api.get<FollowUp[]>("/api/v1/followups", { include_completed: false }, signal),
  );

  async function runDiscovery() {
    await run("discover", async () => {
      try {
        await api.post("/api/v1/jobs/discover", {});
        toast.success("Discovery run started.");
        dashboard.reload();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Discovery failed.");
      }
    });
  }

  async function completeFollowUp(id: string) {
    await run(`followup-${id}`, async () => {
      const ok = await toast.withToast(
        () => api.post(`/api/v1/followups/${id}/complete`),
        "Follow-up marked complete.",
        "Could not complete the follow-up",
      );
      if (ok !== undefined) {
        followups.reload();
        dashboard.reload();
      }
    });
  }

  return (
    <>
      <PageHeader
        title="Overview"
        description="Everything the agent did for you, and everything waiting on a decision."
        actions={
          <>
            <Button onClick={() => dashboard.reload()}>Refresh</Button>
            <Button variant="primary" loading={isPending("discover")} onClick={() => void runDiscovery()}>
              Run discovery
            </Button>
          </>
        }
      />

      <AsyncBoundary
        loading={dashboard.loading}
        error={dashboard.error}
        data={dashboard.data}
        onRetry={dashboard.reload}
        loadingLabel="Loading your dashboard…"
      >
        {(data) => (
          <>
            <StatGrid>
              {Object.entries(data.counts ?? {}).map(([key, value]) => {
                const href = COUNT_LINKS[key];
                return (
                  <StatTile
                    key={key}
                    label={titleize(key)}
                    value={value}
                    href={href}
                    tone={COUNT_TONES[key] ?? "neutral"}
                  />
                );
              })}
            </StatGrid>

            <CardGrid columns={2}>
              <Card title="Daily run" description="Status of the scheduled discovery + scoring pass.">
                {data.daily_run ? (
                  <dl className="def-list">
                    <dt>Status</dt>
                    <dd>
                      <StatusBadge value={data.daily_run.status || "unknown"} />
                    </dd>
                    <dt>Last run</dt>
                    <dd>
                      {formatDateTime(data.daily_run.last_run_at)}
                      {data.daily_run.last_run_at && (
                        <span className="cell-sub">{relativeTime(data.daily_run.last_run_at)}</span>
                      )}
                    </dd>
                    <dt>Next run</dt>
                    <dd>{formatDateTime(data.daily_run.next_run_at)}</dd>
                  </dl>
                ) : (
                  <EmptyState
                    title="No run recorded yet"
                    description="Schedule a discovery agent to populate this."
                    action={<Link href="/automations">Open automations</Link>}
                  />
                )}
              </Card>

              <Card
                title="Application cap"
                description="Guardrail so the agent never over-applies in a single day."
              >
                {data.application_cap ? (
                  <UsageMeter
                    label="Applications used today"
                    used={data.application_cap.used_today}
                    total={data.application_cap.cap}
                  />
                ) : (
                  <EmptyState title="No cap configured" description="Set a daily cap in preferences." />
                )}
              </Card>

              <Card title="AI usage vs budget" description="Spend tracked against your monthly budget.">
                {data.ai_usage ? (
                  <>
                    <UsageMeter
                      label="Estimated month-to-date spend"
                      used={data.ai_usage.estimated_cost_month_usd}
                      total={data.ai_usage.budget_usd}
                      formatValue={formatUsd}
                    />
                    <dl className="def-list">
                      <dt>Requests today</dt>
                      <dd>{data.ai_usage.requests_today}</dd>
                      <dt>Tokens today</dt>
                      <dd>{data.ai_usage.tokens_today.toLocaleString()}</dd>
                    </dl>
                  </>
                ) : (
                  <EmptyState title="AI is not configured" description="Connect a provider under Integrations." />
                )}
              </Card>

              <Card
                title="Integration health"
                description="Per-source connection state from the last sync attempt."
                actions={<Link href="/sources">Manage sources</Link>}
              >
                {data.integration_health?.length ? (
                  <ul className="list-rows">
                    {data.integration_health.map((item) => (
                      <li className="list-row" key={item.name}>
                        <div className="list-row-main">
                          <strong>{item.name}</strong>
                          <span>
                            {item.last_success_at
                              ? `Last success ${relativeTime(item.last_success_at)}`
                              : "No successful sync yet"}
                          </span>
                          {item.last_error && <span className="field-error">{item.last_error}</span>}
                        </div>
                        <StatusBadge value={item.health} />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState
                    title="No job sources configured"
                    description="Add a source so the agent has somewhere to look."
                    action={<Link href="/sources">Add a source</Link>}
                  />
                )}
              </Card>
            </CardGrid>

            <CardGrid columns={2}>
              <Card title="Follow-ups due" description="Nudges the agent scheduled on your behalf.">
                <AsyncBoundary
                  loading={followups.loading}
                  error={followups.error}
                  data={followups.data}
                  onRetry={followups.reload}
                  isEmpty={(items) => items.length === 0}
                  empty={<EmptyState title="Nothing due" description="No follow-ups are waiting." />}
                >
                  {(items) => (
                    <ul className="list-rows">
                      {items.map((item) => (
                        <li className="list-row" key={item.id}>
                          <div className="list-row-main">
                            <strong>{titleize(item.kind)}</strong>
                            <span>
                              Due {relativeTime(item.due_date)}
                              {item.company ? ` · ${item.company}` : ""}
                              {item.job_title ? ` · ${item.job_title}` : ""}
                            </span>
                            {item.note && <span>{item.note}</span>}
                          </div>
                          <div className="list-row-actions">
                            <Link className="btn btn-ghost btn-sm" href={`/applications/${item.application_id}`}>
                              <span>Open</span>
                            </Link>
                            <Button
                              size="sm"
                              loading={isPending(`followup-${item.id}`)}
                              onClick={() => void completeFollowUp(item.id)}
                            >
                              Complete
                            </Button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </AsyncBoundary>
              </Card>

              <Card title="Recent activity" description="The audit trail, newest first.">
                {data.recent_activity?.length ? (
                  <ul className="timeline">
                    {data.recent_activity.map((item, index) => (
                      <li key={`${item.created_at}-${index}`}>
                        <div>
                          <p className="timeline-title">{titleize(item.action)}</p>
                          <p className="timeline-meta">{formatDateTime(item.created_at)}</p>
                          {item.summary && <p className="timeline-body">{item.summary}</p>}
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState title="No activity yet" description="Actions will appear here as the agent runs." />
                )}
              </Card>
            </CardGrid>
          </>
        )}
      </AsyncBoundary>
    </>
  );
}
