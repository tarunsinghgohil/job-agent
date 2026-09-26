"use client";

import { useEffect, useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card, CardGrid } from "../../components/Card";
import { FieldRow, Input, Textarea } from "../../components/Field";
import { FormActions } from "../../components/FormActions";
import { PageHeader } from "../../components/PageHeader";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { Toggle } from "../../components/Toggle";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { numberFieldValue, toNumberOrNull } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import type { Profile } from "../../lib/types";

const EMPTY_EXPERIENCE = { company: "", title: "", location: "", description: "", is_current: false };
const EMPTY_PROJECT = { name: "", role: "", description: "", url: "" };
const EMPTY_EDUCATION = { institution: "", degree: "", field_of_study: "" };
const EMPTY_SKILL = { name: "", years: null as number | null };
const EMPTY_FACT = { kind: "summary", statement: "", detail: "" };

export function ProfileView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const profile = useResource<Profile>((signal) => api.get<Profile>("/api/v1/profile", undefined, signal));
  const [form, setForm] = useState<Profile | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (profile.data && !form) setForm(profile.data);
  }, [profile.data, form]);

  const [expDraft, setExpDraft] = useState(EMPTY_EXPERIENCE);
  const [projDraft, setProjDraft] = useState(EMPTY_PROJECT);
  const [eduDraft, setEduDraft] = useState(EMPTY_EDUCATION);
  const [skillDraft, setSkillDraft] = useState(EMPTY_SKILL);
  const [factDraft, setFactDraft] = useState(EMPTY_FACT);

  function set<K extends keyof Profile>(key: K, value: Profile[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current));
    setDirty(true);
  }

  async function save() {
    if (!form) return;
    await run("save", async () => {
      await toast.withToast(() => api.put("/api/v1/profile", form), "Profile saved.", "Could not save the profile");
      setDirty(false);
      profile.reload();
    });
  }

  async function addExperience() {
    if (!expDraft.company.trim() || !expDraft.title.trim()) {
      toast.error("Company and title are required.");
      return;
    }
    await run("add-exp", async () => {
      await toast.withToast(() => api.post("/api/v1/profile/experiences", { ...expDraft, highlights: [], tech_stack: [] }), "Experience added.");
      setExpDraft(EMPTY_EXPERIENCE);
      profile.reload();
      setForm(null);
    });
  }

  async function removeExperience(id: string) {
    await run(`del-exp-${id}`, async () => {
      await api.del(`/api/v1/profile/experiences/${id}`);
      profile.reload();
      setForm(null);
    });
  }

  async function addProject() {
    if (!projDraft.name.trim()) {
      toast.error("Project name is required.");
      return;
    }
    await run("add-proj", async () => {
      await toast.withToast(() => api.post("/api/v1/profile/projects", { ...projDraft, tech_stack: [], highlights: [] }), "Project added.");
      setProjDraft(EMPTY_PROJECT);
      profile.reload();
      setForm(null);
    });
  }

  async function removeProject(id: string) {
    await run(`del-proj-${id}`, async () => {
      await api.del(`/api/v1/profile/projects/${id}`);
      profile.reload();
      setForm(null);
    });
  }

  async function addEducation() {
    if (!eduDraft.institution.trim()) {
      toast.error("Institution is required.");
      return;
    }
    await run("add-edu", async () => {
      await toast.withToast(() => api.post("/api/v1/profile/education", eduDraft), "Education added.");
      setEduDraft(EMPTY_EDUCATION);
      profile.reload();
      setForm(null);
    });
  }

  async function removeEducation(id: string) {
    await run(`del-edu-${id}`, async () => {
      await api.del(`/api/v1/profile/education/${id}`);
      profile.reload();
      setForm(null);
    });
  }

  async function addSkill() {
    if (!skillDraft.name.trim()) {
      toast.error("Skill name is required.");
      return;
    }
    await run("add-skill", async () => {
      await toast.withToast(() => api.post("/api/v1/profile/skills", skillDraft), "Skill added.");
      setSkillDraft(EMPTY_SKILL);
      profile.reload();
      setForm(null);
    });
  }

  async function removeSkill(id: string) {
    await run(`del-skill-${id}`, async () => {
      await api.del(`/api/v1/profile/skills/${id}`);
      profile.reload();
      setForm(null);
    });
  }

  async function addFact() {
    if (!factDraft.statement.trim()) {
      toast.error("The fact needs a statement.");
      return;
    }
    await run("add-fact", async () => {
      await toast.withToast(() => api.post("/api/v1/profile/facts", { ...factDraft, tags: [] }), "Fact added.");
      setFactDraft(EMPTY_FACT);
      profile.reload();
      setForm(null);
    });
  }

  async function removeFact(id: string) {
    await run(`del-fact-${id}`, async () => {
      await api.del(`/api/v1/profile/facts/${id}`);
      profile.reload();
      setForm(null);
    });
  }

  return (
    <>
      <PageHeader
        title="Career profile"
        description="The canonical, factual source of truth. AI generation may only cite what is stored here."
      />

      <AsyncBoundary loading={profile.loading} error={profile.error} data={form ?? profile.data} onRetry={profile.reload}>
        {(data) => (
          <>
            <Card title="Basics">
              <FieldRow>
                <Input label="Full name" value={data.full_name} onChange={(e) => set("full_name", e.target.value)} />
                <Input label="Headline" value={data.headline} onChange={(e) => set("headline", e.target.value)} />
              </FieldRow>
              <FieldRow>
                <Input label="Email" type="email" value={data.email} onChange={(e) => set("email", e.target.value)} />
                <Input label="Phone" value={data.phone} onChange={(e) => set("phone", e.target.value)} />
              </FieldRow>
              <Input label="Location" value={data.location} onChange={(e) => set("location", e.target.value)} />
              <Textarea label="Summary" rows={3} value={data.summary} onChange={(e) => set("summary", e.target.value)} />
              <FieldRow columns={3}>
                <Input
                  label="Total experience (years)"
                  type="number"
                  value={numberFieldValue(data.total_experience_years)}
                  onChange={(e) => set("total_experience_years", Number(e.target.value) || 0)}
                />
                <Input
                  label="Current CTC (LPA)"
                  type="number"
                  value={numberFieldValue(data.current_ctc_lpa)}
                  onChange={(e) => set("current_ctc_lpa", toNumberOrNull(e.target.value))}
                />
                <Input
                  label="Expected CTC (LPA)"
                  type="number"
                  value={numberFieldValue(data.expected_ctc_lpa)}
                  onChange={(e) => set("expected_ctc_lpa", toNumberOrNull(e.target.value))}
                />
              </FieldRow>
              <Input label="Notice period" value={data.notice_period} onChange={(e) => set("notice_period", e.target.value)} />
              <FieldRow>
                <Toggle label="Work authorization" checked={data.work_authorization} onChange={(v) => set("work_authorization", v)} />
                <Toggle label="Open to relocation" checked={data.open_to_relocation} onChange={(v) => set("open_to_relocation", v)} />
              </FieldRow>
              <FormActions onSave={save} saving={isPending("save")} dirty={dirty} />
            </Card>

            <CardGrid columns={2}>
              <Card title="Experience">
                <ul className="list-rows">
                  {(data.experiences ?? []).map((exp) => (
                    <li className="list-row" key={exp.id}>
                      <div className="list-row-main">
                        <strong>
                          {exp.title} at {exp.company}
                        </strong>
                        <span>{exp.location}</span>
                        {exp.description && <span>{exp.description}</span>}
                      </div>
                      <Button size="sm" variant="danger" loading={isPending(`del-exp-${exp.id}`)} onClick={() => void removeExperience(exp.id)}>
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
                <FieldRow>
                  <Input label="Company" value={expDraft.company} onChange={(e) => setExpDraft((d) => ({ ...d, company: e.target.value }))} />
                  <Input label="Title" value={expDraft.title} onChange={(e) => setExpDraft((d) => ({ ...d, title: e.target.value }))} />
                </FieldRow>
                <Textarea
                  label="Description"
                  rows={2}
                  value={expDraft.description}
                  onChange={(e) => setExpDraft((d) => ({ ...d, description: e.target.value }))}
                />
                <Button loading={isPending("add-exp")} onClick={() => void addExperience()}>
                  Add experience
                </Button>
              </Card>

              <Card title="Projects">
                <ul className="list-rows">
                  {(data.projects ?? []).map((p) => (
                    <li className="list-row" key={p.id}>
                      <div className="list-row-main">
                        <strong>{p.name}</strong>
                        {p.description && <span>{p.description}</span>}
                      </div>
                      <Button size="sm" variant="danger" loading={isPending(`del-proj-${p.id}`)} onClick={() => void removeProject(p.id)}>
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
                <FieldRow>
                  <Input label="Name" value={projDraft.name} onChange={(e) => setProjDraft((d) => ({ ...d, name: e.target.value }))} />
                  <Input label="Role" value={projDraft.role} onChange={(e) => setProjDraft((d) => ({ ...d, role: e.target.value }))} />
                </FieldRow>
                <Button loading={isPending("add-proj")} onClick={() => void addProject()}>
                  Add project
                </Button>
              </Card>

              <Card title="Education">
                <ul className="list-rows">
                  {(data.education ?? []).map((edu) => (
                    <li className="list-row" key={edu.id}>
                      <div className="list-row-main">
                        <strong>{edu.institution}</strong>
                        <span>
                          {edu.degree} {edu.field_of_study}
                        </span>
                      </div>
                      <Button size="sm" variant="danger" loading={isPending(`del-edu-${edu.id}`)} onClick={() => void removeEducation(edu.id)}>
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
                <FieldRow>
                  <Input
                    label="Institution"
                    value={eduDraft.institution}
                    onChange={(e) => setEduDraft((d) => ({ ...d, institution: e.target.value }))}
                  />
                  <Input label="Degree" value={eduDraft.degree} onChange={(e) => setEduDraft((d) => ({ ...d, degree: e.target.value }))} />
                </FieldRow>
                <Button loading={isPending("add-edu")} onClick={() => void addEducation()}>
                  Add education
                </Button>
              </Card>

              <Card title="Skills">
                <div className="chips-row">
                  {(data.skills ?? []).map((skill) => (
                    <Badge key={skill.id} tone={skill.is_primary ? "accent" : "neutral"}>
                      {skill.name}
                      {skill.years != null ? ` (${skill.years}y)` : ""}{" "}
                      <button
                        type="button"
                        className="chip-remove"
                        aria-label={`Remove ${skill.name}`}
                        onClick={() => void removeSkill(skill.id)}
                      >
                        ×
                      </button>
                    </Badge>
                  ))}
                </div>
                <FieldRow>
                  <Input label="Skill name" value={skillDraft.name} onChange={(e) => setSkillDraft((d) => ({ ...d, name: e.target.value }))} />
                  <Input
                    label="Years"
                    type="number"
                    value={numberFieldValue(skillDraft.years)}
                    onChange={(e) => setSkillDraft((d) => ({ ...d, years: toNumberOrNull(e.target.value) }))}
                  />
                </FieldRow>
                <Button loading={isPending("add-skill")} onClick={() => void addSkill()}>
                  Add skill
                </Button>
              </Card>
            </CardGrid>

            <Card title="Career facts" description="The atomic, citable claims AI generation is allowed to reference.">
              {(data.facts ?? []).length > 0 ? (
                <ul className="list-rows">
                  {(data.facts ?? []).map((fact) => (
                    <li className="list-row" key={fact.id}>
                      <div className="list-row-main">
                        <strong>{fact.statement}</strong>
                        {fact.detail && <span>{fact.detail}</span>}
                      </div>
                      <Button size="sm" variant="danger" loading={isPending(`del-fact-${fact.id}`)} onClick={() => void removeFact(fact.id)}>
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title="No facts recorded" />
              )}
              <Textarea
                label="New fact"
                rows={2}
                value={factDraft.statement}
                onChange={(e) => setFactDraft((d) => ({ ...d, statement: e.target.value }))}
              />
              <Button loading={isPending("add-fact")} onClick={() => void addFact()}>
                Add fact
              </Button>
            </Card>
          </>
        )}
      </AsyncBoundary>
    </>
  );
}
