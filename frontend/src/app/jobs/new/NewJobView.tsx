"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "../../../components/Button";
import { Card } from "../../../components/Card";
import { FieldRow, Input, Select, Textarea } from "../../../components/Field";
import { PageHeader } from "../../../components/PageHeader";
import { Toggle } from "../../../components/Toggle";
import { useToast } from "../../../components/Toast";
import { api } from "../../../lib/api";
import { numberFieldValue, toNumberOrNull } from "../../../lib/format";
import { usePending } from "../../../lib/hooks";
import type { Job, JobCreateInput } from "../../../lib/types";

const EMPLOYMENT_OPTIONS = [
  { value: "full_time", label: "Full-time" },
  { value: "part_time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "internship", label: "Internship" },
];

const EMPTY: JobCreateInput = {
  title: "",
  company: "",
  location: "",
  is_remote: false,
  url: "",
  apply_url: "",
  description: "",
  salary_min_lpa: null,
  salary_max_lpa: null,
  employment_type: "full_time",
  industry: "",
  experience_min_years: null,
  experience_max_years: null,
  posted_at: null,
  source_name: "manual",
};

export function NewJobView() {
  const router = useRouter();
  const toast = useToast();
  const { isPending, run } = usePending();
  const [form, setForm] = useState<JobCreateInput>(EMPTY);

  function set<K extends keyof JobCreateInput>(key: K, value: JobCreateInput[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit() {
    if (!form.title.trim() || !form.company.trim()) {
      toast.error("Title and company are required.");
      return;
    }
    await run("create", async () => {
      const created = await toast.withToast(
        () => api.post<Job>("/api/v1/jobs", form),
        "Job added and scored.",
        "Could not add the job",
      );
      if (created) router.push(`/jobs/${created.id}`);
    });
  }

  return (
    <>
      <PageHeader
        breadcrumb={<Link href="/jobs">← All jobs</Link>}
        title="Add a job manually"
        description="Score a posting the agent did not discover on its own."
      />

      <Card>
        <FieldRow>
          <Input label="Title" required value={form.title} onChange={(e) => set("title", e.target.value)} />
          <Input label="Company" required value={form.company} onChange={(e) => set("company", e.target.value)} />
        </FieldRow>
        <FieldRow>
          <Input label="Location" value={form.location} onChange={(e) => set("location", e.target.value)} />
          <Select
            label="Employment type"
            options={EMPLOYMENT_OPTIONS}
            value={form.employment_type}
            onChange={(e) => set("employment_type", e.target.value)}
          />
        </FieldRow>
        <Toggle
          label="Remote"
          checked={form.is_remote}
          onChange={(v) => set("is_remote", v)}
        />
        <FieldRow>
          <Input label="Job posting URL" value={form.url} onChange={(e) => set("url", e.target.value)} />
          <Input label="Apply URL (optional)" value={form.apply_url} onChange={(e) => set("apply_url", e.target.value)} />
        </FieldRow>
        <FieldRow columns={3}>
          <Input
            label="Min salary (LPA)"
            type="number"
            value={numberFieldValue(form.salary_min_lpa)}
            onChange={(e) => set("salary_min_lpa", toNumberOrNull(e.target.value))}
          />
          <Input
            label="Max salary (LPA)"
            type="number"
            value={numberFieldValue(form.salary_max_lpa)}
            onChange={(e) => set("salary_max_lpa", toNumberOrNull(e.target.value))}
          />
          <Input label="Industry" value={form.industry} onChange={(e) => set("industry", e.target.value)} />
        </FieldRow>
        <FieldRow>
          <Input
            label="Min experience (years)"
            type="number"
            value={numberFieldValue(form.experience_min_years)}
            onChange={(e) => set("experience_min_years", toNumberOrNull(e.target.value))}
          />
          <Input
            label="Max experience (years)"
            type="number"
            value={numberFieldValue(form.experience_max_years)}
            onChange={(e) => set("experience_max_years", toNumberOrNull(e.target.value))}
          />
        </FieldRow>
        <Textarea
          label="Description"
          rows={10}
          hint="The full job description — this is what the matcher scores against."
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
        />
        <div className="form-actions">
          <div />
          <div className="form-actions-right">
            <Button variant="ghost" onClick={() => router.push("/jobs")}>
              Cancel
            </Button>
            <Button variant="primary" loading={isPending("create")} onClick={() => void submit()}>
              Add and score
            </Button>
          </div>
        </div>
      </Card>
    </>
  );
}
