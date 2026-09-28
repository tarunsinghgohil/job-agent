"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";
import { Badge, StatusBadge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { Pagination } from "../../components/Pagination";
import { ScoreBar } from "../../components/ScoreBar";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { Input, Select } from "../../components/Field";
import { Table } from "../../components/Table";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { formatDate, formatSalary, titleize } from "../../lib/format";
import { useDebounced, usePending, useResource } from "../../lib/hooks";
import type { Job, Paginated } from "../../lib/types";
import { useState } from "react";

const DECISION_OPTIONS = [
  { value: "HIGH_PRIORITY", label: "High priority" },
  { value: "REVIEW", label: "Review" },
  { value: "REJECT", label: "Reject" },
];

const STATUS_OPTIONS = [
  { value: "new", label: "New" },
  { value: "qualified", label: "Qualified" },
  { value: "rejected", label: "Rejected" },
  { value: "queued", label: "Queued" },
  { value: "applied", label: "Applied" },
  { value: "archived", label: "Archived" },
];

export function JobsView() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const { isPending, run } = usePending();

  const status = params.get("status") ?? "";
  const decision = params.get("decision") ?? "";
  const q = params.get("q") ?? "";
  const page = Number(params.get("page") ?? "1");
  const pageSize = Number(params.get("page_size") ?? "25");
  const sortParam = params.get("sort") ?? "score";
  const order = params.get("order") ?? "desc";

  const [qDraft, setQDraft] = useState(q);
  const debouncedQ = useDebounced(qDraft);

  const setParam = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      if (key !== "page") next.set("page", "1");
      router.push(`/jobs?${next.toString()}`);
    },
    [params, router],
  );

  useMemo(() => {
    if (debouncedQ !== q) setParam("q", debouncedQ);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);

  const jobs = useResource<Paginated<Job>>(
    (signal) =>
      api.get<Paginated<Job>>(
        "/api/v1/jobs",
        { status, decision, q, page, page_size: pageSize, sort: sortParam, order },
        signal,
      ),
    [status, decision, q, page, pageSize, sortParam, order],
  );

  async function runDiscovery() {
    await run("discover", async () => {
      await toast.withToast(
        () => api.post("/api/v1/jobs/discover", {}),
        "Discovery finished.",
        "Discovery failed",
      );
      jobs.reload();
    });
  }

  async function rescoreAll() {
    await run("rescore-all", async () => {
      await toast.withToast(
        () => api.post("/api/v1/jobs/rescore-all"),
        "Every job was re-scored.",
        "Re-scoring failed",
      );
      jobs.reload();
    });
  }

  function sortValue(): string {
    return order === "desc" ? `-${sortParam}` : sortParam;
  }

  function onSortChange(next: string) {
    const field = next.startsWith("-") ? next.slice(1) : next;
    const nextOrder = next.startsWith("-") ? "desc" : "asc";
    const p = new URLSearchParams(params.toString());
    p.set("sort", field);
    p.set("order", nextOrder);
    router.push(`/jobs?${p.toString()}`);
  }

  return (
    <>
      <PageHeader
        title="Jobs"
        description="Every job the agent has seen, scored against your current policy."
        actions={
          <>
            <Link href="/jobs/new" className="btn btn-secondary btn-md">
              <span>Add manually</span>
            </Link>
            <Button loading={isPending("rescore-all")} onClick={() => void rescoreAll()}>
              Re-score all
            </Button>
            <Button variant="primary" loading={isPending("discover")} onClick={() => void runDiscovery()}>
              Run discovery
            </Button>
          </>
        }
      />

      <div className="toolbar">
        <Input
          placeholder="Search title, company, description…"
          value={qDraft}
          onChange={(e) => setQDraft(e.target.value)}
          aria-label="Search jobs"
        />
        <Select
          placeholder="Any status"
          options={STATUS_OPTIONS}
          value={status}
          onChange={(e) => setParam("status", e.target.value)}
          aria-label="Filter by status"
        />
        <Select
          placeholder="Any decision"
          options={DECISION_OPTIONS}
          value={decision}
          onChange={(e) => setParam("decision", e.target.value)}
          aria-label="Filter by decision"
        />
      </div>

      <AsyncBoundary
        loading={jobs.loading}
        error={jobs.error}
        data={jobs.data}
        onRetry={jobs.reload}
        isEmpty={(d) => d.items.length === 0}
        empty={
          <EmptyState
            title="No jobs match these filters"
            description="Run discovery, add a job manually, or clear the filters."
            action={
              <Link href="/jobs/new" className="btn btn-secondary btn-sm">
                <span>Add a job</span>
              </Link>
            }
          />
        }
      >
        {(data) => (
          <>
            <Table<Job>
              rowKey={(row) => row.id}
              sort={sortValue()}
              onSortChange={onSortChange}
              onRowClick={(row) => router.push(`/jobs/${row.id}`)}
              columns={[
                {
                  key: "score",
                  header: "Score",
                  sortKey: "score",
                  width: "160px",
                  render: (row) =>
                    row.match ? (
                      <div className="score-cell">
                        <ScoreBar score={row.match.score} compact />
                        <StatusBadge value={row.match.decision} />
                      </div>
                    ) : (
                      <span className="muted">Not scored</span>
                    ),
                },
                {
                  key: "title",
                  header: "Role",
                  sortKey: "title",
                  render: (row) => (
                    <div>
                      <p className="cell-title">{row.title}</p>
                      <p className="cell-sub">{row.company}</p>
                    </div>
                  ),
                },
                {
                  key: "location",
                  header: "Location",
                  render: (row) => (
                    <span>
                      {row.location || "—"}
                      {row.is_remote && <Badge tone="accent">Remote</Badge>}
                    </span>
                  ),
                },
                {
                  key: "salary",
                  header: "Salary",
                  render: (row) => formatSalary(row.salary_min_lpa, row.salary_max_lpa, row.currency),
                },
                {
                  key: "source",
                  header: "Source",
                  render: (row) => titleize(row.source_name),
                },
                {
                  key: "apply_method",
                  header: "Apply method",
                  render: (row) =>
                    row.application_email ? (
                      <Badge tone="success" title={`The agent can email this application to ${row.application_email}`}>
                        Auto (email)
                      </Badge>
                    ) : (
                      <Badge tone="neutral" title="No published apply email; you submit this one yourself">
                        Manual
                      </Badge>
                    ),
                },
                {
                  key: "posted",
                  header: "Posted",
                  sortKey: "created_at",
                  render: (row) => formatDate(row.posted_at ?? row.created_at),
                },
                {
                  key: "status",
                  header: "Status",
                  render: (row) => <StatusBadge value={row.status} />,
                },
              ]}
              rows={data.items}
            />
            <Pagination
              page={data.page}
              pages={data.pages}
              total={data.total}
              pageSize={data.page_size}
              onPageChange={(p) => setParam("page", String(p))}
              onPageSizeChange={(size) => setParam("page_size", String(size))}
            />
          </>
        )}
      </AsyncBoundary>
    </>
  );
}
