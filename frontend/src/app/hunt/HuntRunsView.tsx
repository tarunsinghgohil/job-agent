"use client";

import { StatusBadge } from "../../components/Badge";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { Table } from "../../components/Table";
import { api } from "../../lib/api";
import { formatDateTime, formatDuration, titleize } from "../../lib/format";
import { useResource } from "../../lib/hooks";
import type { HuntRun, JsonObject } from "../../lib/types";

function count(summary: JsonObject, key: string): string {
  const value = summary[key];
  return typeof value === "number" ? String(value) : "—";
}

export function HuntRunsView() {
  const runs = useResource<HuntRun[]>((signal) => api.get<HuntRun[]>("/api/v1/hunt/runs", { limit: 25 }, signal));

  return (
    <AsyncBoundary
      loading={runs.loading}
      error={runs.error}
      data={runs.data}
      onRetry={runs.reload}
      isEmpty={(d) => d.length === 0}
      empty={<EmptyState title="No runs yet" description="Runs appear here after 'Run hunt now' or a scheduled run." />}
    >
      {(data) => (
        <Table<HuntRun>
          rowKey={(row) => row.id}
          columns={[
            { key: "when", header: "Started", render: (row) => formatDateTime(row.started_at) },
            { key: "trigger", header: "Trigger", render: (row) => titleize(row.trigger) },
            { key: "status", header: "Status", render: (row) => <StatusBadge value={row.status} /> },
            {
              key: "queries",
              header: "Queries",
              align: "right",
              render: (row) => (Array.isArray(row.summary.queries) ? String(row.summary.queries.length) : "—"),
            },
            { key: "new", header: "New jobs", align: "right", render: (row) => count(row.summary, "created") },
            { key: "first", header: "Apply first", align: "right", render: (row) => count(row.summary, "apply_first") },
            { key: "review", header: "Review", align: "right", render: (row) => count(row.summary, "review") },
            {
              key: "detail",
              header: "Notes",
              render: (row) => {
                const errors = Array.isArray(row.summary.source_errors) ? row.summary.source_errors.length : 0;
                const warnings = Array.isArray(row.summary.warnings) ? (row.summary.warnings as string[]) : [];
                const parts = [
                  row.error,
                  errors ? `${errors} source error${errors === 1 ? "" : "s"}` : "",
                  ...warnings,
                ].filter(Boolean);
                return parts.length ? <span className="muted">{parts.join(" · ")}</span> : <span className="faint">—</span>;
              },
            },
            { key: "duration", header: "Took", align: "right", render: (row) => formatDuration(row.duration_ms) },
          ]}
          rows={data}
        />
      )}
    </AsyncBoundary>
  );
}
