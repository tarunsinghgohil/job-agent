"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, StatusBadge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { Card, CardGrid } from "../../../components/Card";
import { FieldRow, Input, Select, Textarea } from "../../../components/Field";
import { PageHeader } from "../../../components/PageHeader";
import { AsyncBoundary, EmptyState } from "../../../components/States";
import { useToast } from "../../../components/Toast";
import { api } from "../../../lib/api";
import { formatDate, formatDateTime, titleize } from "../../../lib/format";
import { usePending, useResource } from "../../../lib/hooks";
import type { Application, PrepareResult } from "../../../lib/types";

export function ApplicationDetailView({ applicationId }: { applicationId: string }) {
  const toast = useToast();
  const { isPending, run } = usePending();
  const [followUpDate, setFollowUpDate] = useState("");
  const [followUpNote, setFollowUpNote] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [prepareResult, setPrepareResult] = useState<PrepareResult | null>(null);

  const application = useResource<Application>(
    (signal) => api.get<Application>(`/api/v1/applications/${applicationId}`, undefined, signal),
    [applicationId],
  );

  async function act(action: string, body?: unknown, successMessage?: string) {
    await run(action, async () => {
      const ok = await toast.withToast(
        () => api.post(`/api/v1/applications/${applicationId}/${action}`, body ?? {}),
        successMessage ?? "Done.",
        `Could not ${action}`,
      );
      if (ok !== undefined) application.reload();
    });
  }

  async function prepare() {
    await run("prepare", async () => {
      const result = await toast.withToast(
        () => api.post<PrepareResult>(`/api/v1/applications/${applicationId}/prepare`),
        "Application prepared.",
        "Preparation failed",
      );
      if (result) {
        setPrepareResult(result);
        application.reload();
      }
    });
  }

  /**
   * `confirmManual: false` asks the agent to send it (email lane only).
   * `true` records a submission the user made themselves, which is the only
   * option for LinkedIn and company portals.
   */
  async function submit(confirmManual: boolean) {
    await act(
      "submit",
      { confirm_manual_submission: confirmManual },
      confirmManual ? "Recorded as submitted." : "Application sent.",
    );
  }

  async function submitManual() {
    await run("submit-manual", async () => {
      const ok = await toast.withToast(
        () => api.post(`/api/v1/applications/${applicationId}/submit`, { confirm_manual_submission: true }),
        "Recorded as submitted.",
        "Could not record the submission",
      );
      if (ok !== undefined) application.reload();
    });
  }

  async function addFollowUp() {
    if (!followUpDate) {
      toast.error("Pick a due date first.");
      return;
    }
    await run("followup", async () => {
      const ok = await toast.withToast(
        () => api.post(`/api/v1/applications/${applicationId}/followups`, { due_date: followUpDate, note: followUpNote }),
        "Follow-up scheduled.",
        "Could not schedule the follow-up",
      );
      if (ok !== undefined) {
        setFollowUpDate("");
        setFollowUpNote("");
        application.reload();
      }
    });
  }

  return (
    <AsyncBoundary loading={application.loading} error={application.error} data={application.data} onRetry={application.reload}>
      {(data) => (
        <>
          <PageHeader
            breadcrumb={<Link href="/applications">← Applications</Link>}
            title={data.job_title || data.job_id}
            description={data.company}
            actions={<StatusBadge value={data.status} />}
          />

          <Card
            title="Actions"
            actions={
              <>
                {data.status === "pending_review" && (
                  <>
                    <Button loading={isPending("approve")} onClick={() => void act("approve", {}, "Approved.")}>
                      Approve
                    </Button>
                    <Button variant="ghost" loading={isPending("reject")} onClick={() => void act("reject", { reason: rejectReason }, "Rejected.")}>
                      Reject
                    </Button>
                  </>
                )}
                {data.status === "approved" && (
                  <Button loading={isPending("prepare")} onClick={() => void prepare()}>
                    Prepare
                  </Button>
                )}
                {(data.status === "approved" || data.status === "prepared") && (
                  <>
                    {data.channel === "email" && (
                      <Button
                        variant="primary"
                        loading={isPending("submit")}
                        onClick={() => void submit(false)}
                        title="The agent emails this to the address the posting published"
                      >
                        Send by email
                      </Button>
                    )}
                    <Button
                      variant={data.channel === "email" ? "secondary" : "primary"}
                      loading={isPending("submit-manual")}
                      onClick={() => void submitManual()}
                      title="Record an application you submitted yourself"
                    >
                      Mark as submitted
                    </Button>
                  </>
                )}
                {data.status === "failed" && (
                  <Button
                    loading={isPending("retry")}
                    onClick={() => void act("status", { status: "approved", reason: "Retrying after a failed send" }, "Ready to retry.")}
                  >
                    Retry
                  </Button>
                )}
              </>
            }
          >
            {data.status === "failed" && data.failure_reason && (
              <p className="inline-error" role="alert">
                <strong>The last submission attempt failed.</strong> {data.failure_reason}
              </p>
            )}
            {data.status === "pending_review" && (
              <Input
                label="Rejection reason (optional)"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
              />
            )}
            {data.channel === "linkedin" && (data.status === "approved" || data.status === "prepared") && (
              <p className="inline-note">
                LinkedIn is a manual lane. Apply on LinkedIn yourself, then Submit here records it — this
                product never automates LinkedIn submission.
              </p>
            )}
            {prepareResult && (
              <div className="prose">
                <p>
                  Generated {prepareResult.assets_generated.length} asset(s), resolved{" "}
                  {prepareResult.answers_resolved} answer(s) ({prepareResult.answers_needing_review} need review).
                </p>
                {prepareResult.warnings.length > 0 && (
                  <ul>
                    {prepareResult.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </Card>

          <CardGrid columns={2}>
            <Card title="Details">
              <dl className="def-list">
                <dt>Channel</dt>
                <dd>{titleize(data.channel)}</dd>
                <dt>Match score</dt>
                <dd>{data.match_score != null ? data.match_score.toFixed(0) : "—"}</dd>
                <dt>Approved</dt>
                <dd>{formatDateTime(data.approved_at)}</dd>
                <dt>Submitted</dt>
                <dd>{formatDateTime(data.submitted_at)}</dd>
                <dt>Next action</dt>
                <dd>{data.next_action || "—"}</dd>
                <dt>Notes</dt>
                <dd>{data.notes || "—"}</dd>
              </dl>
              <Link href={`/jobs/${data.job_id}`}>View job posting →</Link>
            </Card>

            <Card title="Status history">
              {data.history && data.history.length > 0 ? (
                <ul className="timeline">
                  {data.history.map((h) => (
                    <li key={h.id}>
                      <div>
                        <p className="timeline-title">
                          {titleize(h.from_status || "created")} → {titleize(h.to_status)}
                        </p>
                        <p className="timeline-meta">
                          {formatDateTime(h.created_at)} · {h.actor}
                        </p>
                        {h.reason && <p className="timeline-body">{h.reason}</p>}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title="No history yet" />
              )}
            </Card>
          </CardGrid>

          <Card title="Generated assets">
            {data.assets && data.assets.length > 0 ? (
              data.assets
                .filter((a) => a.is_current)
                .map((asset) => (
                  <div key={asset.id} className="code-block">
                    <p className="cell-sub">{titleize(asset.asset_type)}</p>
                    <pre>{asset.content}</pre>
                  </div>
                ))
            ) : (
              <EmptyState title="Nothing generated yet" description="Prepare the application to generate assets." />
            )}
          </Card>

          <Card title="Answers used">
            {data.answers && data.answers.length > 0 ? (
              <ul className="list-rows">
                {data.answers.map((a) => (
                  <li className="list-row" key={a.id}>
                    <div className="list-row-main">
                      <strong>{a.question}</strong>
                      <span>{a.answer}</span>
                    </div>
                    <Badge tone={a.state === "verified" ? "success" : a.state === "inferred" ? "warning" : "danger"}>
                      {titleize(a.state)}
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No answers resolved yet" />
            )}
          </Card>

          <Card title="Follow-ups">
            {data.followups && data.followups.length > 0 && (
              <ul className="list-rows">
                {data.followups.map((f) => (
                  <li className="list-row" key={f.id}>
                    <div className="list-row-main">
                      <strong>{titleize(f.kind)}</strong>
                      <span>Due {formatDate(f.due_date)}</span>
                      {f.note && <span>{f.note}</span>}
                    </div>
                    {f.completed_at ? (
                      <Badge tone="success">Done</Badge>
                    ) : (
                      <Button
                        size="sm"
                        loading={isPending(`fu-${f.id}`)}
                        onClick={() =>
                          run(`fu-${f.id}`, async () => {
                            await toast.withToast(() => api.post(`/api/v1/followups/${f.id}/complete`), "Marked done.");
                            application.reload();
                          })
                        }
                      >
                        Mark done
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <FieldRow columns={3}>
              <Input type="date" label="Due date" value={followUpDate} onChange={(e) => setFollowUpDate(e.target.value)} />
              <Input label="Note" value={followUpNote} onChange={(e) => setFollowUpNote(e.target.value)} />
              <div style={{ display: "flex", alignItems: "flex-end" }}>
                <Button loading={isPending("followup")} onClick={() => void addFollowUp()}>
                  Schedule
                </Button>
              </div>
            </FieldRow>
          </Card>
        </>
      )}
    </AsyncBoundary>
  );
}
