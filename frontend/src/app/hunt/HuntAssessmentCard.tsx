"use client";

import Link from "next/link";
import { Badge } from "../../components/Badge";
import { Card } from "../../components/Card";
import { ScoreBreakdown } from "../../components/ScoreBar";
import { AsyncBoundary } from "../../components/States";
import { api } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { useResource } from "../../lib/hooks";
import type { HuntJobDetail } from "../../lib/types";
import {
  EXPERIENCE_LABEL,
  STRENGTH_LABEL,
  STRENGTH_TONE,
  WORK_MODE_LABEL,
  applyLinkText,
  experienceRange,
} from "./huntFormat";

/** The Job Hunt verdict for one job, with the resume evidence behind it. */
export function HuntAssessmentCard({ jobId, reloadKey = 0 }: { jobId: string; reloadKey?: number }) {
  const detail = useResource<HuntJobDetail>(
    (signal) => api.get<HuntJobDetail>(`/api/v1/hunt/jobs/${jobId}`, undefined, signal),
    [jobId, reloadKey],
  );

  return (
    <Card
      title="Job Hunt"
      description="Where this job lands on your shortlist, and why."
      actions={
        <Link href="/hunt" className="btn btn-ghost btn-sm">
          <span>Open shortlist</span>
        </Link>
      }
    >
      <AsyncBoundary loading={detail.loading} error={detail.error} data={detail.data} onRetry={detail.reload}>
        {(data) => {
          const a = data.assessment;
          if (!a) return <p className="muted">This job has not been ranked by the hunt yet.</p>;
          const link = applyLinkText(a);
          return (
            <div className="hunt-detail">
              <p className="try-result-head">
                <strong>{a.section}</strong>
                <Badge tone={STRENGTH_TONE[a.strength]}>{STRENGTH_LABEL[a.strength]}</Badge>
                <span className="mono">{Math.round(a.score)}/100</span>
              </p>
              <p className="prose">{a.explanation}</p>

              <dl className="def-list">
                <dt>Work mode</dt>
                <dd>
                  {WORK_MODE_LABEL[a.work_mode] ?? a.work_mode}
                  {a.remote_region ? ` · ${a.remote_region}` : ""}
                  {a.tier_name ? ` · priority "${a.tier_name}"` : ""}
                </dd>
                <dt>Experience</dt>
                <dd>
                  {experienceRange(a.experience_min_years, a.experience_max_years)} · {EXPERIENCE_LABEL[a.experience_fit]} ·{" "}
                  {a.seniority} level
                </dd>
                <dt>Skills</dt>
                <dd>
                  {a.skill_overlap != null
                    ? `${Math.round(a.skill_overlap * 100)}% of the listed skills`
                    : "No recognised skills listed"}
                </dd>
                <dt>Originally posted</dt>
                <dd>{a.posted_at ? formatDateTime(a.posted_at) : "Not provided by the source"}</dd>
                <dt>Updated at source</dt>
                <dd>{a.source_updated_at ? formatDateTime(a.source_updated_at) : "Not provided"}</dd>
                <dt>First found</dt>
                <dd>{a.first_seen_at ? formatDateTime(a.first_seen_at) : "—"}</dd>
                <dt>Apply link</dt>
                <dd>
                  <Badge tone={link.tone} title={link.title}>
                    {link.text}
                  </Badge>
                </dd>
                {a.public_contact_email && (
                  <>
                    <dt>Public contact</dt>
                    <dd>
                      <a href={`mailto:${a.public_contact_email}`}>{a.public_contact_email}</a>
                    </dd>
                  </>
                )}
              </dl>

              {a.reasons.length > 0 && (
                <ul className="hunt-warnings is-danger">
                  {a.reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              )}
              {a.warnings.length > 0 && (
                <ul className="hunt-warnings">
                  {a.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}

              <h3 className="card-title">Hunt score breakdown</h3>
              <ScoreBreakdown breakdown={a.breakdown} weights={data.breakdown_max} />

              <h3 className="card-title">Resume evidence for this job</h3>
              {data.evidence.length === 0 ? (
                <p className="muted">
                  No resume passages matched. Upload a resume under <Link href="/resumes">Resumes</Link> to see which of
                  your projects support this role.
                </p>
              ) : (
                <ul className="evidence-list">
                  {data.evidence.map((e) => (
                    <li key={e.evidence_id}>
                      <p>{e.content.length > 360 ? `${e.content.slice(0, 360)}…` : e.content}</p>
                      <p className="faint">{e.source}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        }}
      </AsyncBoundary>
    </Card>
  );
}
