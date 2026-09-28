"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card, CardGrid } from "../../components/Card";
import { FieldRow, Input, Select, Textarea } from "../../components/Field";
import { FormActions } from "../../components/FormActions";
import { ConfirmDialog } from "../../components/Modal";
import { AsyncBoundary } from "../../components/States";
import { SuggestInput } from "../../components/SuggestInput";
import { TagInput } from "../../components/TagInput";
import { Toggle } from "../../components/Toggle";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { clearSuggestionCache } from "../../lib/suggest";
import { formatDateTime, numberFieldValue, toNumberOrNull } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import { HUNT_SENIORITY_LEVELS } from "../../lib/types";
import type {
  HuntConfig,
  HuntPreviewResult,
  HuntProfileSuggestions,
  HuntQueryPreview,
  HuntSeniority,
} from "../../lib/types";
import { CRON_PRESETS, EXPERIENCE_LABEL, STRENGTH_LABEL, STRENGTH_TONE, WEIGHT_KEYS, WEIGHT_LABELS } from "./huntFormat";
import { TierEditor } from "./TierEditor";

const SEMANTIC_OPTIONS = [
  { value: "local", label: "Local similarity (free, offline)" },
  { value: "embeddings", label: "OpenAI embeddings (uses AI budget)" },
  { value: "off", label: "Off" },
];

function mergeUnique(current: string[], extra: string[]): string[] {
  const out = [...current];
  for (const value of extra) {
    if (value && !out.some((v) => v.toLowerCase() === value.toLowerCase())) out.push(value);
  }
  return out;
}

function QueryPreview({ form, onLoaded }: { form: HuntConfig; onLoaded: (labels: string[]) => void }) {
  const { isPending, run } = usePending();
  const toast = useToast();
  const [preview, setPreview] = useState<HuntQueryPreview | null>(null);

  async function load() {
    await run("preview", async () => {
      const result = await toast.withToast(
        () => api.post<HuntQueryPreview>("/api/v1/hunt/queries/preview", form),
        "Query preview updated.",
        "Could not preview queries",
      );
      if (result) {
        setPreview(result);
        onLoaded(result.queries.map((q) => q.label));
      }
    });
  }

  useEffect(() => {
    void api.post<HuntQueryPreview>("/api/v1/hunt/queries/preview", form).then((result) => {
      setPreview(result);
      onLoaded(result.queries.map((q) => q.label));
    }, () => undefined);
    // Load once with the saved form; later previews are on demand.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="query-preview">
      <div className="query-preview-head">
        <Button size="sm" loading={isPending("preview")} onClick={() => void load()}>
          Preview queries
        </Button>
        {preview && (
          <span className="muted">
            {preview.queries.length} queries go to {preview.search_sources} search source
            {preview.search_sources === 1 ? "" : "s"}. {preview.board_sources} company board
            {preview.board_sources === 1 ? "" : "s"} run once.
          </span>
        )}
      </div>
      {preview && preview.queries.length > 0 && (
        <ol className="query-list">
          {preview.queries.map((query) => (
            <li key={`${query.label}-${query.location}-${query.remote}`}>
              <span>{query.label}</span>
              {query.origin === "custom" ? <Badge tone="accent">custom</Badge> : null}
              {query.remote ? <Badge tone="info">remote</Badge> : null}
            </li>
          ))}
        </ol>
      )}
      {preview && preview.search_sources === 0 && (
        <p className="inline-note">
          None of your enabled sources supports keyword search, so these queries will not be sent.{" "}
          <Link href="/sources">Add Remotive or Adzuna</Link> to search by query.
        </p>
      )}
    </div>
  );
}

function TryIt({ form }: { form: HuntConfig }) {
  const toast = useToast();
  const { isPending, run } = usePending();
  const [title, setTitle] = useState("Senior React Developer");
  const [location, setLocation] = useState("Jaipur");
  const [description, setDescription] = useState("");
  const [isRemote, setIsRemote] = useState(false);
  const [result, setResult] = useState<HuntPreviewResult | null>(null);

  async function test() {
    await run("try", async () => {
      const response = await toast.withToast(
        () =>
          api.post<HuntPreviewResult>("/api/v1/hunt/preview", {
            title,
            location,
            description,
            is_remote: isRemote,
            config: form,
          }),
        "Assessed with your current (unsaved) setup.",
        "Could not assess",
      );
      if (response) setResult(response);
    });
  }

  return (
    <Card
      title="Try it"
      description="Paste any posting to see where it would land. Uses the settings on this page, even unsaved ones. Nothing is stored."
    >
      <FieldRow>
        <SuggestInput label="Title" suggest="role" value={title} onChange={setTitle} required />
        <SuggestInput label="Location" suggest="location" value={location} onChange={setLocation} placeholder="e.g. Remote - India" />
      </FieldRow>
      <Textarea
        label="Description"
        rows={5}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Paste the job description, including experience and skills"
      />
      <FieldRow>
        <Toggle label="Marked remote by the source" checked={isRemote} onChange={setIsRemote} />
        <div className="align-right">
          <Button variant="primary" loading={isPending("try")} disabled={!title.trim()} onClick={() => void test()}>
            Assess
          </Button>
        </div>
      </FieldRow>

      {result && (
        <div className={`try-result kind-${result.category}`} role="status">
          <p className="try-result-head">
            <strong>{result.section}</strong>
            <Badge tone={STRENGTH_TONE[result.strength]}>{STRENGTH_LABEL[result.strength]}</Badge>
            <span className="mono">{Math.round(result.score)}/100</span>
          </p>
          <p className="muted">
            {result.work_mode}
            {result.remote_region ? ` · ${result.remote_region}` : ""} · {result.seniority} · experience{" "}
            {EXPERIENCE_LABEL[result.experience_fit]}
            {result.skill_overlap != null ? ` · ${Math.round(result.skill_overlap * 100)}% skill overlap` : ""}
          </p>
          <p>{result.explanation}</p>
          {result.reasons.length > 0 && (
            <ul className="hunt-warnings is-danger">
              {result.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          {result.warnings.length > 0 && (
            <ul className="hunt-warnings">
              {result.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

export function HuntSetupView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const config = useResource<HuntConfig>((signal) => api.get<HuntConfig>("/api/v1/hunt/config", undefined, signal));
  const [form, setForm] = useState<HuntConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [queryLabels, setQueryLabels] = useState<string[]>([]);

  useEffect(() => {
    if (config.data && !form) setForm(config.data);
  }, [config.data, form]);

  function set<K extends keyof HuntConfig>(key: K, value: HuntConfig[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current));
    setDirty(true);
  }

  function toggleSeniority(level: HuntSeniority) {
    if (!form) return;
    const current = form.excluded_seniority;
    set("excluded_seniority", current.includes(level) ? current.filter((l) => l !== level) : [...current, level]);
  }

  async function save() {
    if (!form) return;
    if (form.location_tiers.some((t) => !t.name.trim())) {
      toast.error("Every location priority needs a name.");
      return;
    }
    await run("save", async () => {
      const updated = await toast.withToast(
        () => api.put<HuntConfig>("/api/v1/hunt/config", form),
        "Setup saved. Every job was re-ranked.",
        "Could not save",
      );
      if (updated) {
        setForm(updated);
        setDirty(false);
        config.setData(updated);
        clearSuggestionCache();
      }
    });
  }

  async function importProfile() {
    await run("import", async () => {
      const suggestions = await toast.withToast(
        () => api.get<HuntProfileSuggestions>("/api/v1/hunt/profile-suggestions"),
        "Added roles and skills from your profile. Review, then save.",
        "Could not read your profile",
      );
      if (!suggestions || !form) return;
      setForm({
        ...form,
        experience_years: form.experience_years ?? suggestions.experience_years,
        target_roles: mergeUnique(form.target_roles, suggestions.target_roles),
        skills: mergeUnique(form.skills, suggestions.skills),
      });
      setDirty(true);
    });
  }

  async function reset() {
    await run("reset", async () => {
      const updated = await toast.withToast(
        () => api.post<HuntConfig>("/api/v1/hunt/config/reset"),
        "Setup reset to defaults.",
        "Could not reset",
      );
      if (updated) {
        setForm(updated);
        setDirty(false);
        config.setData(updated);
      }
      setConfirmReset(false);
    });
  }

  const cronIsPreset = form ? CRON_PRESETS.some((p) => p.value === form.schedule_cron) : true;

  return (
    <AsyncBoundary loading={config.loading} error={config.error} data={form ?? config.data} onRetry={config.reload}>
      {(data) => (
        <>
          <Card
            title="1. Your profile"
            description="What the hunt matches jobs against. Skills are normalised: React.js and ReactJS count as React, and MERN expands to MongoDB, Express, React and Node."
            actions={
              <Button size="sm" variant="ghost" loading={isPending("import")} onClick={() => void importProfile()}>
                Import from my profile
              </Button>
            }
          >
            <FieldRow columns={3}>
              <Input
                label="Total experience (years)"
                type="number"
                step="0.5"
                min={0}
                value={numberFieldValue(data.experience_years)}
                onChange={(e) => set("experience_years", toNumberOrNull(e.target.value))}
              />
            </FieldRow>
            <TagInput label="Target roles" suggest="role" values={data.target_roles} onChange={(v) => set("target_roles", v)} />
            <TagInput label="Your skills" suggest="skill" values={data.skills} onChange={(v) => set("skills", v)} />
            <TagInput
              label="Related title words"
              suggest="title_word"
              hint="A title containing any of these counts as your job family, e.g. 'Software Engineer - Frontend'."
              values={data.role_keywords}
              onChange={(v) => set("role_keywords", v)}
            />
            <fieldset className="tier-modes">
              <legend className="field-label">Never show these levels</legend>
              {HUNT_SENIORITY_LEVELS.map((level) => (
                <label key={level} className={`mode-pill ${data.excluded_seniority.includes(level) ? "is-on" : ""}`}>
                  <input
                    type="checkbox"
                    checked={data.excluded_seniority.includes(level)}
                    onChange={() => toggleSeniority(level)}
                  />
                  {level}
                </label>
              ))}
            </fieldset>
          </Card>

          <Card
            title="2. Location priorities"
            description="Checked top to bottom; a job lands in the first priority it fits. Apply-first tiers need a strong fit; weaker fits drop to Worth Reviewing."
          >
            <TierEditor tiers={data.location_tiers} country={data.country} onChange={(v) => set("location_tiers", v)} />
            <FieldRow>
              <SuggestInput label="Country" suggest="location" value={data.country} onChange={(v) => set("country", v)} />
              <Toggle
                label="Accept worldwide remote roles"
                hint="Shown under review with a reminder to confirm they hire from your country."
                checked={data.accept_worldwide_remote}
                onChange={(v) => set("accept_worldwide_remote", v)}
              />
            </FieldRow>
            <details className="hunt-details">
              <summary>
                Places that count as {data.country} ({data.country_places.length})
              </summary>
              <TagInput suggest="location" values={data.country_places} onChange={(v) => set("country_places", v)} />
            </details>
          </Card>

          <Card
            title="3. Search queries"
            description="Each target role is searched in each location priority, plus a few skill-combination searches, so jobs with different titles are not missed."
          >
            <FieldRow columns={3}>
              <Toggle label="Generate queries automatically" checked={data.auto_queries} onChange={(v) => set("auto_queries", v)} />
              <Input
                label="Max queries per run"
                type="number"
                min={1}
                max={60}
                value={data.max_queries}
                onChange={(e) => set("max_queries", Number(e.target.value) || 1)}
              />
              <Input
                label="Results per query"
                type="number"
                min={1}
                max={200}
                value={data.results_per_query}
                onChange={(e) => set("results_per_query", Number(e.target.value) || 1)}
              />
            </FieldRow>
            <TagInput
              label="Your own queries"
              suggest="query"
              hint="Always run first, e.g. 'Frontend Engineer AI LLM React Remote'."
              values={data.custom_queries}
              onChange={(v) => set("custom_queries", v)}
            />
            <TagInput
              label="Skip these generated queries"
              suggest={queryLabels}
              hint="Pick from the generated queries to stop one running."
              values={data.excluded_queries}
              onChange={(v) => set("excluded_queries", v)}
            />
            <QueryPreview form={data} onLoaded={setQueryLabels} />
          </Card>

          <Card title="4. Ranking" description="How jobs are scored and filtered. The score is out of 100; weights are relative.">
            <FieldRow columns={3}>
              <Input
                label="Ignore postings older than (days)"
                hint="0 keeps everything"
                type="number"
                min={0}
                value={data.max_age_days}
                onChange={(e) => set("max_age_days", Number(e.target.value) || 0)}
              />
              <Input
                label="Apply-first score bar"
                type="number"
                min={0}
                max={100}
                value={data.apply_first_threshold}
                onChange={(e) => set("apply_first_threshold", Number(e.target.value) || 0)}
              />
              <Input
                label="Minimum skill overlap (%)"
                type="number"
                min={0}
                max={100}
                value={Math.round(data.min_skill_overlap * 100)}
                onChange={(e) => set("min_skill_overlap", Math.min(100, Math.max(0, Number(e.target.value) || 0)) / 100)}
              />
            </FieldRow>
            <CardGrid columns={4}>
              {WEIGHT_KEYS.map((key) => (
                <Input
                  key={key}
                  label={WEIGHT_LABELS[key].label}
                  hint={WEIGHT_LABELS[key].hint}
                  type="number"
                  min={0}
                  max={100}
                  value={data.weights[key] ?? 0}
                  onChange={(e) => set("weights", { ...data.weights, [key]: Number(e.target.value) || 0 })}
                />
              ))}
            </CardGrid>
            <FieldRow>
              <Select
                label="Semantic matching"
                hint="Compares your resume and profile with each description, beyond exact keywords."
                options={SEMANTIC_OPTIONS}
                value={data.semantic_mode}
                onChange={(e) => set("semantic_mode", e.target.value as HuntConfig["semantic_mode"])}
              />
              <Toggle
                label="Apply my Preferences filters"
                hint="Uses excluded companies, excluded keywords and the minimum salary from Preferences."
                checked={data.respect_policy_filters}
                onChange={(v) => set("respect_policy_filters", v)}
              />
            </FieldRow>
          </Card>

          <Card title="5. Automation and alerts">
            <FieldRow>
              <Toggle
                label="Run the hunt automatically"
                hint={
                  data.schedule_enabled && data.next_run_at && !dirty
                    ? `Next run ${formatDateTime(data.next_run_at)}`
                    : "Searches your sources on the schedule below."
                }
                checked={data.schedule_enabled}
                onChange={(v) => set("schedule_enabled", v)}
              />
              <Select
                label="Schedule"
                options={[...CRON_PRESETS, { value: "custom", label: "Custom cron expression" }]}
                value={cronIsPreset ? data.schedule_cron : "custom"}
                onChange={(e) => set("schedule_cron", e.target.value === "custom" ? data.schedule_cron : e.target.value)}
              />
            </FieldRow>
            {!cronIsPreset && (
              <Input
                label="Cron expression"
                hint="minute hour day month weekday, in the server timezone"
                value={data.schedule_cron}
                onChange={(e) => set("schedule_cron", e.target.value)}
              />
            )}
            <Toggle
              label="Alert me about new apply-first matches"
              hint={
                <>
                  Sent through the channels routed for high-match jobs in <Link href="/notifications">Notifications</Link>.
                </>
              }
              checked={data.notify_new_matches}
              onChange={(v) => set("notify_new_matches", v)}
            />
          </Card>

          <TryIt form={data} />

          <FormActions
            onSave={() => void save()}
            onCancel={() => {
              setForm(config.data);
              setDirty(false);
            }}
            onReset={() => setConfirmReset(true)}
            saving={isPending("save")}
            dirty={dirty}
            saveLabel="Save and re-rank"
            note={dirty ? "You have unsaved changes." : data.updated_at ? `Saved ${formatDateTime(data.updated_at)}` : undefined}
          />

          <ConfirmDialog
            open={confirmReset}
            title="Reset the Job Hunt setup?"
            message="Roles, skills, location priorities, queries and ranking go back to the defaults. The schedule is kept."
            confirmLabel="Reset"
            destructive
            busy={isPending("reset")}
            onConfirm={() => void reset()}
            onCancel={() => setConfirmReset(false)}
          />
        </>
      )}
    </AsyncBoundary>
  );
}
