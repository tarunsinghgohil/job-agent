"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Input, Select } from "../../components/Field";
import { Pagination } from "../../components/Pagination";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { StatGrid, StatTile } from "../../components/StatTile";
import { Table } from "../../components/Table";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { relativeTime } from "../../lib/format";
import { useDebounced, usePending, useResource } from "../../lib/hooks";
import type { HuntBoard, HuntItem, HuntRun, JsonObject, Paginated } from "../../lib/types";
import { HuntJobCard } from "./HuntJobCard";

const FRESH_OPTIONS = [
  { value: "24", label: "Last 24 hours" },
  { value: "72", label: "Last 3 days" },
  { value: "168", label: "Last 7 days" },
  { value: "720", label: "Last 30 days" },
];

function num(summary: JsonObject, key: string): number {
  const value = summary[key];
  return typeof value === "number" ? value : 0;
}

function LastRun({ board }: { board: HuntBoard }) {
  const summary = board.last_run_summary ?? {};
  const errors = Array.isArray(summary.source_errors) ? (summary.source_errors as JsonObject[]) : [];
  const queries = Array.isArray(summary.queries) ? summary.queries.length : 0;
  if (!board.last_run_at) {
    return <p className="muted hunt-lastrun">The hunt has not run yet.</p>;
  }
  return (
    <div className="hunt-lastrun">
      <p className="muted">
        Last run {relativeTime(board.last_run_at)}
        {summary.discovered ? ` · ${queries} queries · ${num(summary, "created")} new jobs` : " · re-rank only"}
        {` · ${num(summary, "assessed")} ranked`}
      </p>
      {errors.length > 0 && (
        <details className="hunt-errors">
          <summary>
            {errors.length} source{errors.length === 1 ? "" : "s"} failed during the last run
          </summary>
          <ul>
            {errors.map((err, index) => (
              <li key={index}>
                <strong>{String(err.source_name ?? "Source")}</strong>: {String(err.error ?? "")}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function NotMatchList({ q, fresh }: { q: string; fresh: string }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const results = useResource<Paginated<HuntItem>>(
    (signal) =>
      api.get<Paginated<HuntItem>>(
        "/api/v1/hunt/results",
        { category: "not_match", q, fresh_within_hours: fresh, page, page_size: pageSize },
        signal,
      ),
    [q, fresh, page, pageSize],
  );
  return (
    <AsyncBoundary
      loading={results.loading}
      error={results.error}
      data={results.data}
      onRetry={results.reload}
      isEmpty={(d) => d.items.length === 0}
      empty={<p className="muted">Nothing was ruled out.</p>}
    >
      {(data) => (
        <>
          <Table<HuntItem>
            rowKey={(row) => row.job_id}
            columns={[
              {
                key: "role",
                header: "Role",
                render: (row) => (
                  <div>
                    <p className="cell-title">
                      <Link href={`/jobs/${row.job_id}`}>{row.title}</Link>
                    </p>
                    <p className="cell-sub">{row.company}</p>
                  </div>
                ),
              },
              { key: "location", header: "Location", render: (row) => row.location || "—" },
              {
                key: "why",
                header: "Why it was ruled out",
                render: (row) => <span>{row.reasons.join("; ")}</span>,
              },
            ]}
            rows={data.items}
          />
          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={data.page_size}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        </>
      )}
    </AsyncBoundary>
  );
}

export function HuntBoardView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const [qDraft, setQDraft] = useState("");
  const q = useDebounced(qDraft);
  const [fresh, setFresh] = useState("");
  const [showNotMatch, setShowNotMatch] = useState(false);

  const board = useResource<HuntBoard>(
    (signal) =>
      api.get<HuntBoard>("/api/v1/hunt/board", { q, fresh_within_hours: fresh, limit_per_section: 50 }, signal),
    [q, fresh],
  );

  async function runHunt(discover: boolean) {
    await run(discover ? "run" : "rerank", async () => {
      const result = await toast.withToast(
        () => api.post<HuntRun>("/api/v1/hunt/run", { discover }),
        discover ? "Hunt finished." : "Jobs re-ranked.",
        "The hunt failed",
      );
      if (result && result.status === "failed") {
        toast.error(`The hunt failed: ${result.error || "see Run history"}`);
      } else if (result && typeof result.summary.detail === "string") {
        toast.info(result.summary.detail);
      }
      board.reload();
    });
  }

  return (
    <>
      <div className="toolbar hunt-toolbar">
        <Input
          placeholder="Filter by title, company or location…"
          value={qDraft}
          onChange={(e) => setQDraft(e.target.value)}
          aria-label="Filter the shortlist"
          wrapperClassName="grow"
        />
        <Select
          placeholder="Any freshness"
          options={FRESH_OPTIONS}
          value={fresh}
          onChange={(e) => setFresh(e.target.value)}
          aria-label="Freshness filter"
        />
        <div className="button-row">
          <Button loading={isPending("rerank")} disabled={isPending("run")} onClick={() => void runHunt(false)}>
            Re-rank only
          </Button>
          <Button
            variant="primary"
            loading={isPending("run")}
            loadingLabel="Hunting…"
            disabled={isPending("rerank")}
            onClick={() => void runHunt(true)}
          >
            Run hunt now
          </Button>
        </div>
      </div>

      <AsyncBoundary loading={board.loading && !board.data} error={board.error} data={board.data} onRetry={board.reload}>
        {(data) => (
          <>
            {data.sources_enabled === 0 && (
              <p className="inline-note hunt-note">
                No job sources are enabled, so a hunt can only rank jobs you add by hand.{" "}
                <Link href="/sources">Add a source</Link>: Remotive is free and needs no key, and Adzuna India needs a
                free app id and key.
              </p>
            )}

            <StatGrid>
              <StatTile label="Fresh today" value={data.stats.fresh_today} hint="Relevant roles from the last 24h" tone="info" />
              <StatTile label="Apply first" value={data.stats.apply_first} hint="Strong fits in your top locations" tone="success" />
              <StatTile label="Worth reviewing" value={data.stats.review} hint="Weaker fits or lower-priority places" tone="warning" />
              <StatTile label="Remote" value={data.stats.remote} hint="Among relevant roles" />
            </StatGrid>

            {data.stats.by_tier.length > 0 && (
              <div className="hunt-tier-counts" aria-label="Relevant roles per location priority">
                {data.stats.by_tier.map((tier) => (
                  <span key={tier.name} className="hunt-tier-count">
                    {tier.name} <strong>{tier.count}</strong>
                  </span>
                ))}
              </div>
            )}

            <LastRun board={data} />

            {data.stats.total === 0 ? (
              <EmptyState
                title="No jobs on the board yet"
                description="Run the hunt to search your enabled sources, or add a job manually. Every job is ranked against your Setup."
                action={
                  <Link href="/jobs/new" className="btn btn-secondary btn-sm">
                    <span>Add a job manually</span>
                  </Link>
                }
              />
            ) : data.sections.length === 0 ? (
              <EmptyState
                title="Nothing matches yet"
                description="Every job found so far was ruled out. Check the reasons below, or widen your location priorities in Setup."
              />
            ) : (
              data.sections.map((section) => (
                <section key={section.key} className={`hunt-section kind-${section.kind}`}>
                  <header className="hunt-section-head">
                    <h2 className="hunt-section-title">{section.label}</h2>
                    <Badge tone={section.kind === "apply_first" ? "success" : "warning"}>{section.count}</Badge>
                  </header>
                  <div className="hunt-grid">
                    {section.items.map((item) => (
                      <HuntJobCard key={item.job_id} item={item} />
                    ))}
                  </div>
                  {section.count > section.items.length && (
                    <p className="faint">
                      Showing the top {section.items.length} of {section.count}. Narrow with the filters above.
                    </p>
                  )}
                </section>
              ))
            )}

            {data.not_match.count > 0 && (
              <section className="hunt-section kind-not_match">
                <header className="hunt-section-head">
                  <h2 className="hunt-section-title">Not a Match</h2>
                  <Badge tone="neutral">{data.not_match.count}</Badge>
                  <Button variant="ghost" size="sm" onClick={() => setShowNotMatch((v) => !v)} aria-expanded={showNotMatch}>
                    {showNotMatch ? "Hide" : "Show"} list
                  </Button>
                </header>
                <div className="hunt-reasons">
                  {data.not_match.top_reasons.map((r) => (
                    <span key={r.reason} className="hunt-tier-count">
                      {r.reason} <strong>{r.count}</strong>
                    </span>
                  ))}
                </div>
                {showNotMatch && <NotMatchList q={q} fresh={fresh} />}
              </section>
            )}
          </>
        )}
      </AsyncBoundary>
    </>
  );
}
