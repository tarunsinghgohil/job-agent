"use client";

import { useEffect, useState } from "react";
import { Button } from "../../components/Button";
import { Card, CardGrid } from "../../components/Card";
import { FieldRow, Input } from "../../components/Field";
import { FormActions } from "../../components/FormActions";
import { PageHeader } from "../../components/PageHeader";
import { AsyncBoundary } from "../../components/States";
import { TagInput } from "../../components/TagInput";
import { Toggle } from "../../components/Toggle";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { numberFieldValue, toNumberOrNull } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import type { Preferences } from "../../lib/types";

export function PreferencesView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const prefs = useResource<Preferences>((signal) => api.get<Preferences>("/api/v1/preferences", undefined, signal));
  const [form, setForm] = useState<Preferences | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (prefs.data && !form) setForm(prefs.data);
  }, [prefs.data, form]);

  function set<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current));
    setDirty(true);
  }

  function setWeight(key: string, value: number) {
    setForm((current) => (current ? { ...current, scoring_weights: { ...current.scoring_weights, [key]: value } } : current));
    setDirty(true);
  }

  async function save() {
    if (!form) return;
    await run("save", async () => {
      await toast.withToast(() => api.put("/api/v1/preferences", form), "Preferences saved.", "Could not save");
      setDirty(false);
      prefs.reload();
    });
  }

  async function resetWeights() {
    await run("reset-weights", async () => {
      const updated = await toast.withToast(
        () => api.post<Preferences>("/api/v1/preferences/reset-weights"),
        "Weights reset to defaults.",
      );
      if (updated) {
        setForm(updated);
        setDirty(false);
      }
    });
  }

  return (
    <>
      <PageHeader
        title="Job preferences"
        description="Everything the matching engine reads. Nothing here is hard-coded — change it and every job re-scores on request."
      />

      <AsyncBoundary loading={prefs.loading} error={prefs.error} data={form ?? prefs.data} onRetry={prefs.reload}>
        {(data) => (
          <>
            <Card title="Roles and locations">
              <TagInput label="Target roles" values={data.target_roles} onChange={(v) => set("target_roles", v)} />
              <TagInput label="Preferred locations" values={data.preferred_locations} onChange={(v) => set("preferred_locations", v)} />
              <FieldRow>
                <Toggle label="Remote OK" checked={data.remote_ok} onChange={(v) => set("remote_ok", v)} />
                <Toggle label="Remote only" checked={data.remote_only} onChange={(v) => set("remote_only", v)} />
              </FieldRow>
            </Card>

            <Card title="Compensation and experience">
              <FieldRow columns={3}>
                <Input
                  label="Minimum salary (LPA)"
                  type="number"
                  value={numberFieldValue(data.min_salary_lpa)}
                  onChange={(e) => set("min_salary_lpa", toNumberOrNull(e.target.value))}
                />
                <Input
                  label="Target salary (LPA)"
                  type="number"
                  value={numberFieldValue(data.target_salary_lpa)}
                  onChange={(e) => set("target_salary_lpa", toNumberOrNull(e.target.value))}
                />
                <Input label="Currency" value={data.currency} onChange={(e) => set("currency", e.target.value)} />
              </FieldRow>
              <FieldRow columns={3}>
                <Input
                  label="Min experience (years)"
                  type="number"
                  value={numberFieldValue(data.experience_min_years)}
                  onChange={(e) => set("experience_min_years", toNumberOrNull(e.target.value))}
                />
                <Input
                  label="Max experience (years)"
                  type="number"
                  value={numberFieldValue(data.experience_max_years)}
                  onChange={(e) => set("experience_max_years", toNumberOrNull(e.target.value))}
                />
                <Input
                  label="Notice period (days)"
                  type="number"
                  value={numberFieldValue(data.notice_period_days)}
                  onChange={(e) => set("notice_period_days", Number(e.target.value) || 0)}
                />
              </FieldRow>
              <TagInput label="Employment types" values={data.employment_types} onChange={(v) => set("employment_types", v)} />
              <TagInput label="Industries" values={data.industries} onChange={(v) => set("industries", v)} />
              <TagInput label="Company types" values={data.company_types} onChange={(v) => set("company_types", v)} />
            </Card>

            <Card title="Companies">
              <TagInput label="Preferred companies" values={data.preferred_companies} onChange={(v) => set("preferred_companies", v)} />
              <TagInput label="Excluded companies" values={data.excluded_companies} onChange={(v) => set("excluded_companies", v)} />
            </Card>

            <Card title="Keywords">
              <TagInput label="Must-have keywords" values={data.must_have_keywords} onChange={(v) => set("must_have_keywords", v)} />
              <TagInput label="Nice-to-have keywords" values={data.nice_to_have_keywords} onChange={(v) => set("nice_to_have_keywords", v)} />
              <TagInput label="Excluded keywords" values={data.excluded_keywords} onChange={(v) => set("excluded_keywords", v)} />
            </Card>

            <Card
              title="Scoring weights"
              description="Sum does not need to equal 100; the score is capped there regardless."
              actions={
                <Button variant="ghost" loading={isPending("reset-weights")} onClick={() => void resetWeights()}>
                  Reset to defaults
                </Button>
              }
            >
              <CardGrid columns={3}>
                {Object.entries(data.scoring_weights).map(([key, value]) => (
                  <Input
                    key={key}
                    label={key.replace(/_/g, " ")}
                    type="number"
                    value={value}
                    onChange={(e) => setWeight(key, Number(e.target.value) || 0)}
                  />
                ))}
              </CardGrid>
              <FieldRow>
                <Input
                  label="Review threshold"
                  type="number"
                  value={data.review_threshold}
                  onChange={(e) => set("review_threshold", Number(e.target.value) || 0)}
                />
                <Input
                  label="High priority threshold"
                  type="number"
                  value={data.high_priority_threshold}
                  onChange={(e) => set("high_priority_threshold", Number(e.target.value) || 0)}
                />
              </FieldRow>
              <FieldRow>
                <Toggle
                  label="Enable semantic (AI) scoring"
                  hint="Blends an AI opinion into the score. Deterministic rules still have final authority."
                  checked={data.semantic_scoring_enabled}
                  onChange={(v) => set("semantic_scoring_enabled", v)}
                />
                {data.semantic_scoring_enabled && (
                  <Input
                    label="Semantic weight (0-1)"
                    type="number"
                    step="0.05"
                    value={data.semantic_weight}
                    onChange={(e) => set("semantic_weight", Number(e.target.value) || 0)}
                  />
                )}
              </FieldRow>
            </Card>

            <Card title="Applications and scheduling">
              <FieldRow>
                <Input
                  label="Daily application cap"
                  type="number"
                  value={data.daily_application_cap}
                  onChange={(e) => set("daily_application_cap", Number(e.target.value) || 0)}
                />
                <Input
                  label="Discovery schedule (cron)"
                  value={data.discovery_schedule_cron}
                  onChange={(e) => set("discovery_schedule_cron", e.target.value)}
                />
              </FieldRow>
              <Input label="Timezone" value={data.timezone} onChange={(e) => set("timezone", e.target.value)} />
              <FieldRow>
                <Toggle
                  label="Approval required before submission"
                  checked={data.approval_required}
                  onChange={(v) => set("approval_required", v)}
                />
                <Toggle
                  label="Let the agent send email applications"
                  hint={
                    "Only applies to postings that publish an application address, and only " +
                    "when approval is off. LinkedIn and company portals always stay manual."
                  }
                  checked={data.auto_submit_enabled}
                  onChange={(v) => set("auto_submit_enabled", v)}
                />
              </FieldRow>
            </Card>

            <FormActions onSave={save} saving={isPending("save")} dirty={dirty} />
          </>
        )}
      </AsyncBoundary>
    </>
  );
}
