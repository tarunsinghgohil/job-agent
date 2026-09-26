"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, StatusBadge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { Card, CardGrid } from "../../../components/Card";
import { PageHeader } from "../../../components/PageHeader";
import { ScoreBar, ScoreBreakdown } from "../../../components/ScoreBar";
import { AsyncBoundary, EmptyState } from "../../../components/States";
import { useToast } from "../../../components/Toast";
import { api } from "../../../lib/api";
import { formatDateTime, formatSalary, titleize } from "../../../lib/format";
import { usePending, useResource } from "../../../lib/hooks";
import type { AiReview, CoverLetterResult, Job, ResumeAdviceResult } from "../../../lib/types";

export function JobDetailView({ jobId }: { jobId: string }) {
  const router = useRouter();
  const toast = useToast();
  const { isPending, run } = usePending();
  const [aiReview, setAiReview] = useState<AiReview | null>(null);
  const [coverLetter, setCoverLetter] = useState<CoverLetterResult | null>(null);
  const [resumeAdvice, setResumeAdvice] = useState<ResumeAdviceResult | null>(null);

  const job = useResource<Job>(
    (signal) => api.get<Job>(`/api/v1/jobs/${jobId}`, undefined, signal),
    [jobId],
  );

  async function rescore() {
    await run("rescore", async () => {
      await toast.withToast(() => api.post(`/api/v1/jobs/${jobId}/rescore`), "Re-scored.", "Re-score failed");
      job.reload();
    });
  }

  async function requestAiReview() {
    await run("ai-review", async () => {
      const result = await toast.withToast(
        () => api.post<AiReview>(`/api/v1/jobs/${jobId}/ai-review`),
        "AI review complete.",
        "AI review failed",
      );
      if (result) setAiReview(result);
    });
  }

  async function requestCoverLetter() {
    await run("cover-letter", async () => {
      const result = await toast.withToast(
        () => api.post<CoverLetterResult>(`/api/v1/jobs/${jobId}/cover-letter`),
        "Cover letter drafted.",
        "Could not generate a cover letter",
      );
      if (result) setCoverLetter(result);
    });
  }

  async function requestResumeAdvice() {
    await run("resume-advice", async () => {
      const result = await toast.withToast(
        () => api.post<ResumeAdviceResult>(`/api/v1/jobs/${jobId}/resume-advice`),
        "Resume advice ready.",
        "Could not generate resume advice",
      );
      if (result) setResumeAdvice(result);
    });
  }

  async function queueApplication(channel: string) {
    await run(`queue-${channel}`, async () => {
      const created = await toast.withToast(
        () => api.post<{ id: string }>("/api/v1/applications", { job_id: jobId, channel }),
        "Application queued.",
        "Could not queue the application",
      );
      if (created) router.push(`/applications/${created.id}`);
    });
  }

  return (
    <AsyncBoundary
      loading={job.loading}
      error={job.error}
      data={job.data}
      onRetry={job.reload}
      loadingLabel="Loading job…"
    >
      {(data) => (
        <>
          <PageHeader
            breadcrumb={<Link href="/jobs">← All jobs</Link>}
            title={data.title}
            description={`${data.company}${data.location ? ` · ${data.location}` : ""}`}
            actions={
              <>
                <Button loading={isPending("rescore")} onClick={() => void rescore()}>
                  Re-score
                </Button>
                {data.application_email && (
                  <Button
                    variant="primary"
                    loading={isPending("queue-email")}
                    onClick={() => void queueApplication("email")}
                    title={`The agent can email this application to ${data.application_email}`}
                  >
                    Queue as email application
                  </Button>
                )}
                <Button
                  variant={data.application_email ? "secondary" : "primary"}
                  loading={isPending("queue-manual")}
                  onClick={() => void queueApplication("manual")}
                >
                  Queue application
                </Button>
              </>
            }
          />

          <CardGrid columns={2}>
            <Card title="Match" description="Deterministic score. Hard rules have final authority.">
              {data.match ? (
                <>
                  <ScoreBar score={data.match.score} label="Overall score" />
                  <StatusBadge value={data.match.decision} />
                  {data.match.hard_fail_reasons.length > 0 && (
                    <div className="inline-note" role="alert">
                      <strong>Hard-fail reasons</strong>
                      <ul>
                        {data.match.hard_fail_reasons.map((reason, i) => (
                          <li key={i}>{reason}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <p className="prose">{data.match.explanation}</p>
                  <h3 className="card-title">Score breakdown</h3>
                  <ScoreBreakdown breakdown={data.match.breakdown} />
                  {data.match.matched_skills.length > 0 && (
                    <>
                      <h3 className="card-title">Matched skills</h3>
                      <div className="chips-row">
                        {data.match.matched_skills.map((s) => (
                          <Badge key={s} tone="success">
                            {s}
                          </Badge>
                        ))}
                      </div>
                    </>
                  )}
                  {data.match.missing_skills.length > 0 && (
                    <>
                      <h3 className="card-title">Not evidenced</h3>
                      <div className="chips-row">
                        {data.match.missing_skills.map((s) => (
                          <Badge key={s} tone="warning">
                            {s}
                          </Badge>
                        ))}
                      </div>
                    </>
                  )}
                  {data.match.recommended_resume_id && (
                    <p className="muted">
                      Recommended resume: {data.match.recommendation_reason || data.match.recommended_resume_id}
                    </p>
                  )}
                </>
              ) : (
                <EmptyState title="Not scored yet" />
              )}
            </Card>

            <Card title="Job details">
              <dl className="def-list">
                <dt>Salary</dt>
                <dd>{formatSalary(data.salary_min_lpa, data.salary_max_lpa, data.currency)}</dd>
                <dt>Employment</dt>
                <dd>{titleize(data.employment_type)}</dd>
                <dt>Industry</dt>
                <dd>{data.industry || "—"}</dd>
                <dt>Experience</dt>
                <dd>
                  {data.experience_min_years ?? "?"}–{data.experience_max_years ?? "?"} years
                </dd>
                <dt>Source</dt>
                <dd>{titleize(data.source_name)}</dd>
                <dt>Status</dt>
                <dd>
                  <StatusBadge value={data.status} />
                </dd>
                <dt>Posted</dt>
                <dd>{formatDateTime(data.posted_at)}</dd>
                <dt>URL</dt>
                <dd>
                  {data.url ? (
                    <a href={data.url} target="_blank" rel="noreferrer">
                      Open posting
                    </a>
                  ) : (
                    "—"
                  )}
                </dd>
                <dt>Apply by email</dt>
                <dd>
                  {data.application_email ? (
                    <span className="mono">{data.application_email}</span>
                  ) : (
                    <span className="muted">No address published — apply through the posting</span>
                  )}
                </dd>
              </dl>
              {data.skills && data.skills.length > 0 && (
                <>
                  <h3 className="card-title">Extracted skills</h3>
                  <div className="chips-row">
                    {data.skills.map((s) => (
                      <Badge key={s.skill_slug} tone={s.is_required ? "accent" : "neutral"}>
                        {s.skill_name}
                      </Badge>
                    ))}
                  </div>
                </>
              )}
            </Card>
          </CardGrid>

          <Card title="Job description">
            <p className="prose">{data.description || "No description stored."}</p>
          </Card>

          <Card
            title="AI assist"
            description="Advisory only — deterministic rules always have final authority over these."
            actions={
              <>
                <Button loading={isPending("ai-review")} onClick={() => void requestAiReview()}>
                  AI review
                </Button>
                <Button loading={isPending("cover-letter")} onClick={() => void requestCoverLetter()}>
                  Cover letter
                </Button>
                <Button loading={isPending("resume-advice")} onClick={() => void requestResumeAdvice()}>
                  Resume advice
                </Button>
              </>
            }
          >
            {aiReview && (
              <div className="prose">
                <h3 className="card-title">AI review — {aiReview.verdict}</h3>
                <p>Local score {aiReview.local_score} vs AI score {aiReview.ai_score}</p>
                <ul>{aiReview.reasons?.map((r, i) => <li key={i}>{r}</li>)}</ul>
                {aiReview.gaps && aiReview.gaps.length > 0 && (
                  <>
                    <strong>Gaps</strong>
                    <ul>{aiReview.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
                  </>
                )}
                {aiReview.pitch && <p><em>{aiReview.pitch}</em></p>}
              </div>
            )}
            {coverLetter && (
              <div className="code-block">
                <h3 className="card-title">Cover letter</h3>
                <pre>{coverLetter.cover_letter}</pre>
              </div>
            )}
            {resumeAdvice && (
              <div className="prose">
                <h3 className="card-title">Resume advice</h3>
                {resumeAdvice.recommended_resume && <p>Use: {resumeAdvice.recommended_resume}</p>}
                {resumeAdvice.headline && <p>Headline: {resumeAdvice.headline}</p>}
                {resumeAdvice.emphasize && resumeAdvice.emphasize.length > 0 && (
                  <>
                    <strong>Emphasize</strong>
                    <ul>{resumeAdvice.emphasize.map((e, i) => <li key={i}>{e}</li>)}</ul>
                  </>
                )}
              </div>
            )}
            {!aiReview && !coverLetter && !resumeAdvice && (
              <p className="muted">Run an AI assist above to see results here.</p>
            )}
          </Card>

          <Card title="Audit timeline">
            {data.events && data.events.length > 0 ? (
              <ul className="timeline">
                {data.events.map((event) => (
                  <li key={event.id}>
                    <div>
                      <p className="timeline-title">{titleize(event.event_type)}</p>
                      <p className="timeline-meta">
                        {formatDateTime(event.created_at)} · {event.actor}
                      </p>
                      {event.message && <p className="timeline-body">{event.message}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No events recorded" />
            )}
          </Card>
        </>
      )}
    </AsyncBoundary>
  );
}
