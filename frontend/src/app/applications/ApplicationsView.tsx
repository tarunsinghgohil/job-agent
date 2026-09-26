"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { Pagination } from "../../components/Pagination";
import { StatusBadge } from "../../components/Badge";
import { Select } from "../../components/Field";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { Table } from "../../components/Table";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { APPLICATION_STATUSES } from "../../lib/types";
import { formatDate, titleize } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import type { Application, Paginated } from "../../lib/types";

const STATUS_OPTIONS = APPLICATION_STATUSES.map((s) => ({ value: s, label: titleize(s) }));

export function ApplicationsView() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const { isPending, run } = usePending();

  const status = params.get("status") ?? "";
  const page = Number(params.get("page") ?? "1");
  const pageSize = Number(params.get("page_size") ?? "25");

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.set("page", "1");
    router.push(`/applications?${next.toString()}`);
  }

  const applications = useResource<Paginated<Application>>(
    (signal) => api.get<Paginated<Application>>("/api/v1/applications", { status, page, page_size: pageSize }, signal),
    [status, page, pageSize],
  );

  async function act(id: string, action: string, body?: unknown) {
    await run(`${action}-${id}`, async () => {
      const ok = await toast.withToast(
        () => api.post(`/api/v1/applications/${id}/${action}`, body ?? {}),
        `Application ${action === "status" ? "updated" : action + "d"}.`,
        `Could not ${action} the application`,
      );
      if (ok !== undefined) applications.reload();
    });
  }

  return (
    <>
      <PageHeader
        title="Applications"
        description="The queue from pending review through submission, interview and offer."
      />

      <div className="toolbar">
        <Select
          placeholder="Every status"
          options={STATUS_OPTIONS}
          value={status}
          onChange={(e) => setParam("status", e.target.value)}
          aria-label="Filter by status"
        />
      </div>

      <AsyncBoundary
        loading={applications.loading}
        error={applications.error}
        data={applications.data}
        onRetry={applications.reload}
        isEmpty={(d) => d.items.length === 0}
        empty={
          <EmptyState
            title="Nothing in the queue"
            description="Queue an application from a job's detail page."
            action={
              <Link href="/jobs" className="btn btn-secondary btn-sm">
                <span>Browse jobs</span>
              </Link>
            }
          />
        }
      >
        {(data) => (
          <>
            <Table<Application>
              rowKey={(row) => row.id}
              onRowClick={(row) => router.push(`/applications/${row.id}`)}
              columns={[
                {
                  key: "role",
                  header: "Role",
                  render: (row) => (
                    <div>
                      <p className="cell-title">{row.job_title || row.job_id}</p>
                      <p className="cell-sub">{row.company}</p>
                    </div>
                  ),
                },
                {
                  key: "status",
                  header: "Status",
                  render: (row) => <StatusBadge value={row.status} />,
                },
                {
                  key: "channel",
                  header: "Channel",
                  render: (row) => titleize(row.channel),
                },
                {
                  key: "score",
                  header: "Match",
                  render: (row) => (row.match_score != null ? row.match_score.toFixed(0) : "—"),
                },
                {
                  key: "created",
                  header: "Queued",
                  render: (row) => formatDate(row.created_at),
                },
                {
                  key: "actions",
                  header: "Actions",
                  render: (row) => (
                    <div className="list-row-actions" onClick={(e) => e.stopPropagation()}>
                      {row.status === "pending_review" && (
                        <>
                          <Button size="sm" loading={isPending(`approve-${row.id}`)} onClick={() => void act(row.id, "approve")}>
                            Approve
                          </Button>
                          <Button size="sm" variant="ghost" loading={isPending(`reject-${row.id}`)} onClick={() => void act(row.id, "reject")}>
                            Reject
                          </Button>
                        </>
                      )}
                      {row.status === "approved" && (
                        <Button size="sm" loading={isPending(`prepare-${row.id}`)} onClick={() => void act(row.id, "prepare")}>
                          Prepare
                        </Button>
                      )}
                      {(row.status === "approved" || row.status === "prepared") && (
                        <Button
                          size="sm"
                          variant="primary"
                          loading={isPending(`submit-${row.id}`)}
                          // The email lane is sent by the agent; every other
                          // lane can only be recorded as already submitted.
                          onClick={() =>
                            void act(row.id, "submit", {
                              confirm_manual_submission: row.channel !== "email",
                            })
                          }
                        >
                          {row.channel === "email" ? "Send" : "Mark submitted"}
                        </Button>
                      )}
                    </div>
                  ),
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
