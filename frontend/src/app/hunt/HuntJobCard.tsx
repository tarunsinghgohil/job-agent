"use client";

import Link from "next/link";
import { Badge } from "../../components/Badge";
import { formatDateTime, formatSalary, titleize } from "../../lib/format";
import type { HuntItem } from "../../lib/types";
import {
  EXPERIENCE_LABEL,
  EXPERIENCE_TONE,
  STRENGTH_LABEL,
  STRENGTH_TONE,
  WORK_MODE_LABEL,
  applyLinkText,
  experienceRange,
} from "./huntFormat";

function freshnessTitle(item: HuntItem): string {
  const lines = [
    `Originally posted: ${item.posted_at ? formatDateTime(item.posted_at) : "not provided by the source"}`,
    `Last updated at source: ${item.source_updated_at ? formatDateTime(item.source_updated_at) : "not provided"}`,
    `First found by the hunt: ${item.first_seen_at ? formatDateTime(item.first_seen_at) : "—"}`,
  ];
  return lines.join("\n");
}

export function HuntJobCard({ item }: { item: HuntItem }) {
  const link = applyLinkText(item);
  const applyHref = item.best_apply_url || item.url;
  const mode = WORK_MODE_LABEL[item.work_mode] ?? titleize(item.work_mode);
  const modeText = item.work_mode === "remote" && item.remote_region ? `${mode} · ${item.remote_region}` : mode;
  const hasSalary = item.salary_min_lpa != null || item.salary_max_lpa != null;
  const isFresh = item.freshness_hours != null && item.freshness_hours <= 24;

  return (
    <article className="hunt-card">
      <header className="hunt-card-head">
        <div className="hunt-card-heading">
          <h3 className="hunt-card-title">
            <Link href={`/jobs/${item.job_id}`}>{item.title}</Link>
          </h3>
          <p className="hunt-card-sub">
            {item.company || "Unknown company"} · {item.location || "Location not stated"}
          </p>
        </div>
        <div className="hunt-card-score" title={`Hunt score ${Math.round(item.score)} / 100`}>
          <Badge tone={STRENGTH_TONE[item.strength]}>{STRENGTH_LABEL[item.strength]}</Badge>
          <span className="hunt-score-number">{Math.round(item.score)}</span>
        </div>
      </header>

      <div className="hunt-card-meta">
        <Badge tone={item.work_mode === "remote" ? "accent" : "neutral"}>{modeText}</Badge>
        <Badge tone={EXPERIENCE_TONE[item.experience_fit]}>
          {experienceRange(item.experience_min_years, item.experience_max_years)}
          {item.experience_min_years != null || item.experience_max_years != null
            ? ` · ${EXPERIENCE_LABEL[item.experience_fit]}`
            : ""}
        </Badge>
        <span title={freshnessTitle(item)}>
          <Badge tone={isFresh ? "success" : "neutral"}>{item.freshness_label}</Badge>
        </span>
        <Badge tone={link.tone} title={link.title}>
          {link.text}
        </Badge>
        {hasSalary && <Badge tone="neutral">{formatSalary(item.salary_min_lpa, item.salary_max_lpa, item.currency)}</Badge>}
        {item.job_status === "applied" && <Badge tone="info">Applied</Badge>}
      </div>

      {(item.matched_skills.length > 0 || item.missing_skills.length > 0) && (
        <div className="hunt-skills" aria-label="Skills">
          {item.matched_skills.map((skill) => (
            <span key={`m-${skill}`} className="hunt-skill is-matched" title="You have this skill">
              {skill}
            </span>
          ))}
          {item.missing_skills.slice(0, 6).map((skill) => (
            <span key={`x-${skill}`} className="hunt-skill is-missing" title="Listed in the job, not in your skills">
              {skill}
            </span>
          ))}
        </div>
      )}

      {item.highlights.length > 0 && <p className="hunt-card-why">{item.highlights.slice(0, 3).join(" · ")}</p>}

      {item.warnings.length > 0 && (
        <ul className="hunt-warnings">
          {item.warnings.slice(0, 3).map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <footer className="hunt-card-actions">
        <Link href={`/jobs/${item.job_id}`} className="btn btn-secondary btn-sm">
          <span>View job</span>
        </Link>
        {applyHref ? (
          <a className="btn btn-primary btn-sm" href={applyHref} target="_blank" rel="noopener noreferrer">
            <span>Apply ↗</span>
          </a>
        ) : null}
        {item.public_contact_email && (
          <a className="hunt-contact" href={`mailto:${item.public_contact_email}`} title="Published in the posting">
            {item.public_contact_email}
          </a>
        )}
        {item.duplicate_sources.length > 0 && (
          <span className="faint hunt-sources">
            Also on {item.duplicate_sources.map((s) => titleize(s)).join(", ")}
          </span>
        )}
      </footer>
    </article>
  );
}
