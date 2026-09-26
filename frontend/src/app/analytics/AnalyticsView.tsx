"use client";

import { useState } from "react";
import { BarChart, LineChart } from "../../components/Charts";
import { Card, CardGrid } from "../../components/Card";
import { PageHeader } from "../../components/PageHeader";
import { Select } from "../../components/Field";
import { AsyncBoundary } from "../../components/States";
import { StatGrid, StatTile } from "../../components/StatTile";
import { api } from "../../lib/api";
import { formatPercent } from "../../lib/format";
import { useResource } from "../../lib/hooks";
import type { Analytics } from "../../lib/types";

const DAY_OPTIONS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

export function AnalyticsView() {
  const [days, setDays] = useState("30");
  const analytics = useResource<Analytics>((signal) => api.get<Analytics>("/api/v1/analytics", { days }, signal), [days]);

  return (
    <>
      <PageHeader
        title="Analytics"
        description="What the funnel says — these surface suggestions, they never change your settings on their own."
        actions={<Select options={DAY_OPTIONS} value={days} onChange={(e) => setDays(e.target.value)} aria-label="Time window" />}
      />

      <AsyncBoundary loading={analytics.loading} error={analytics.error} data={analytics.data} onRetry={analytics.reload}>
        {(data) => (
          <>
            <StatGrid>
              <StatTile label="Jobs discovered" value={data.jobs_discovered} />
              <StatTile label="Jobs qualified" value={data.jobs_qualified} tone="success" />
              <StatTile label="Average match score" value={data.average_match_score.toFixed(0)} />
              <StatTile label="Applications submitted" value={data.applications_submitted} tone="info" />
              <StatTile label="Interview rate" value={formatPercent(data.interview_rate)} tone="success" />
              <StatTile label="Response rate" value={formatPercent(data.response_rate)} />
            </StatGrid>

            <CardGrid columns={2}>
              <Card title="Applications per week">
                <LineChart
                  title="Applications per week"
                  points={data.applications_per_week.map((p) => ({ label: p.week, value: p.count }))}
                />
              </Card>

              <Card title="Top skills requested">
                <BarChart
                  title="Top skills requested"
                  horizontal
                  points={data.top_skills_requested.map((s) => ({ label: s.skill, value: s.count }))}
                />
              </Card>

              <Card title="Source conversion">
                <BarChart
                  title="Source conversion rate"
                  horizontal
                  valueSuffix="%"
                  points={data.source_conversion.map((s) => ({ label: s.source, value: s.rate }))}
                />
              </Card>

              <Card title="Rejection reasons">
                <BarChart
                  title="Rejection reasons"
                  horizontal
                  points={data.rejection_reasons.map((r) => ({ label: r.reason, value: r.count }))}
                />
              </Card>

              <Card title="Resume performance">
                <BarChart
                  title="Applications by resume"
                  horizontal
                  points={data.resume_performance.map((r) => ({ label: r.resume, value: r.applications }))}
                />
              </Card>

              <Card title="Average time to response">
                <p className="stat-value">
                  {data.average_days_to_response != null ? `${data.average_days_to_response.toFixed(1)} days` : "Not enough data yet"}
                </p>
              </Card>
            </CardGrid>
          </>
        )}
      </AsyncBoundary>
    </>
  );
}
