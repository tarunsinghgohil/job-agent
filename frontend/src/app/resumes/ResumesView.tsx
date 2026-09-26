"use client";

import { useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card, CardGrid } from "../../components/Card";
import { FieldRow, Input, Select, Textarea } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { TagInput } from "../../components/TagInput";
import { useToast } from "../../components/Toast";
import { api, downloadFile } from "../../lib/api";
import { formatBytes, formatDateTime, titleize } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import type { Resume, ResumeVersion, TailorResult } from "../../lib/types";

export function ResumesView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const [newName, setNewName] = useState("");
  const [uploadTargets, setUploadTargets] = useState<Record<string, HTMLInputElement | null>>({});
  const [tailorJobQuery, setTailorJobQuery] = useState<Record<string, string>>({});
  const [tailorResult, setTailorResult] = useState<Record<string, TailorResult>>({});
  const [previewText, setPreviewText] = useState<Record<string, string>>({});

  const resumes = useResource<Resume[]>((signal) => api.get<Resume[]>("/api/v1/resumes", undefined, signal));

  async function createResume() {
    if (!newName.trim()) {
      toast.error("Give the resume a name first.");
      return;
    }
    await run("create", async () => {
      const ok = await toast.withToast(
        () => api.post<Resume>("/api/v1/resumes", { name: newName, tags: [], role_focus: [], industry_focus: [], skill_focus: [] }),
        "Resume created.",
        "Could not create the resume",
      );
      if (ok) {
        setNewName("");
        resumes.reload();
      }
    });
  }

  async function upload(resumeId: string, file: File) {
    const form = new FormData();
    form.append("file", file);
    await run(`upload-${resumeId}`, async () => {
      const ok = await toast.withToast(
        () => api.upload<ResumeVersion>(`/api/v1/resumes/${resumeId}/versions`, form),
        "Resume uploaded and parsed.",
        "Upload failed",
      );
      if (ok !== undefined) resumes.reload();
    });
  }

  async function makeDefault(resumeId: string) {
    await run(`default-${resumeId}`, async () => {
      await toast.withToast(() => api.post(`/api/v1/resumes/${resumeId}/default`), "Set as default.");
      resumes.reload();
    });
  }

  async function toggleActive(resume: Resume) {
    await run(`active-${resume.id}`, async () => {
      await toast.withToast(
        () =>
          api.put(`/api/v1/resumes/${resume.id}`, {
            name: resume.name,
            description: resume.description,
            tags: resume.tags,
            role_focus: resume.role_focus,
            industry_focus: resume.industry_focus,
            skill_focus: resume.skill_focus,
            is_active: !resume.is_active,
          }),
        resume.is_active ? "Deactivated." : "Activated.",
      );
      resumes.reload();
    });
  }

  async function updateFocus(resume: Resume, field: "role_focus" | "industry_focus" | "skill_focus", values: string[]) {
    await api.put(`/api/v1/resumes/${resume.id}`, {
      name: resume.name,
      description: resume.description,
      tags: resume.tags,
      role_focus: field === "role_focus" ? values : resume.role_focus,
      industry_focus: field === "industry_focus" ? values : resume.industry_focus,
      skill_focus: field === "skill_focus" ? values : resume.skill_focus,
      is_active: resume.is_active,
    });
    resumes.reload();
  }

  async function preview(versionId: string) {
    await run(`preview-${versionId}`, async () => {
      const detail = await api.get<{ extracted_text: string }>(`/api/v1/resumes/versions/${versionId}`);
      setPreviewText((current) => ({ ...current, [versionId]: detail.extracted_text || "(no text extracted)" }));
    });
  }

  async function download(version: ResumeVersion) {
    await run(`download-${version.id}`, async () => {
      await toast.withToast(
        () => downloadFile(`/api/v1/resumes/versions/${version.id}/download`, version.original_filename || "resume"),
        "Downloaded.",
        "Download failed",
      );
    });
  }

  async function deleteVersion(versionId: string) {
    await run(`del-${versionId}`, async () => {
      await toast.withToast(() => api.del(`/api/v1/resumes/versions/${versionId}`), "Version deleted.");
      resumes.reload();
    });
  }

  async function tailor(resume: Resume) {
    const query = tailorJobQuery[resume.id]?.trim();
    if (!query) {
      toast.error("Enter a job ID to tailor against.");
      return;
    }
    await run(`tailor-${resume.id}`, async () => {
      const result = await toast.withToast(
        () => api.post<TailorResult>(`/api/v1/resumes/${resume.id}/tailor`, { job_id: query, save_as_version: false }),
        "Tailored draft generated.",
        "Tailoring failed",
      );
      if (result) setTailorResult((current) => ({ ...current, [resume.id]: result }));
    });
  }

  async function saveTailored(resume: Resume) {
    const query = tailorJobQuery[resume.id]?.trim();
    if (!query) return;
    await run(`save-tailor-${resume.id}`, async () => {
      await toast.withToast(
        () => api.post(`/api/v1/resumes/${resume.id}/tailor`, { job_id: query, save_as_version: true }),
        "Saved as a new version.",
      );
      resumes.reload();
    });
  }

  return (
    <>
      <PageHeader title="Resumes" description="Upload, tag, and generate job-specific drafts. AI never invents facts." />

      <Card title="Add a resume line">
        <FieldRow>
          <Input label="Name" placeholder="e.g. Frontend React" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <Button variant="primary" loading={isPending("create")} onClick={() => void createResume()}>
              Create
            </Button>
          </div>
        </FieldRow>
      </Card>

      <AsyncBoundary
        loading={resumes.loading}
        error={resumes.error}
        data={resumes.data}
        onRetry={resumes.reload}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="No resumes yet" description="Create one above, then upload a PDF or DOCX." />}
      >
        {(items) => (
          <CardGrid columns={1}>
            {items.map((resume) => (
              <Card
                key={resume.id}
                title={
                  <>
                    {resume.name}{" "}
                    {resume.is_default && <Badge tone="accent">Default</Badge>}
                    {!resume.is_active && <Badge tone="neutral">Inactive</Badge>}
                  </>
                }
                actions={
                  <>
                    {!resume.is_default && (
                      <Button size="sm" loading={isPending(`default-${resume.id}`)} onClick={() => void makeDefault(resume.id)}>
                        Make default
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" loading={isPending(`active-${resume.id}`)} onClick={() => void toggleActive(resume)}>
                      {resume.is_active ? "Deactivate" : "Activate"}
                    </Button>
                  </>
                }
              >
                <FieldRow columns={3}>
                  <TagInput
                    label="Role focus"
                    values={resume.role_focus}
                    onChange={(v) => void updateFocus(resume, "role_focus", v)}
                  />
                  <TagInput
                    label="Industry focus"
                    values={resume.industry_focus}
                    onChange={(v) => void updateFocus(resume, "industry_focus", v)}
                  />
                  <TagInput
                    label="Skill focus"
                    values={resume.skill_focus}
                    onChange={(v) => void updateFocus(resume, "skill_focus", v)}
                  />
                </FieldRow>

                <div className="dropzone">
                  <input
                    ref={(el) => {
                      uploadTargets[resume.id] = el;
                    }}
                    className="hidden-input"
                    type="file"
                    accept=".pdf,.docx"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) void upload(resume.id, file);
                      e.target.value = "";
                    }}
                  />
                  <Button loading={isPending(`upload-${resume.id}`)} onClick={() => uploadTargets[resume.id]?.click()}>
                    Upload PDF or DOCX
                  </Button>
                </div>

                {resume.versions && resume.versions.length > 0 ? (
                  <ul className="list-rows">
                    {resume.versions.map((version) => (
                      <li className="list-row" key={version.id}>
                        <div className="list-row-main">
                          <strong>
                            v{version.version_number} — {version.label || version.original_filename}
                          </strong>
                          <span>
                            {titleize(version.origin)} · {titleize(version.parse_status)} ·{" "}
                            {formatBytes(version.size_bytes)} · {formatDateTime(version.created_at)}
                          </span>
                          {version.extracted_skills && version.extracted_skills.length > 0 && (
                            <span>Skills found: {version.extracted_skills.join(", ")}</span>
                          )}
                          {previewText[version.id] && <p className="prose">{previewText[version.id]}</p>}
                        </div>
                        <div className="list-row-actions">
                          <Button size="sm" variant="ghost" loading={isPending(`preview-${version.id}`)} onClick={() => void preview(version.id)}>
                            Preview
                          </Button>
                          {version.original_filename && (
                            <Button size="sm" variant="ghost" loading={isPending(`download-${version.id}`)} onClick={() => void download(version)}>
                              Download
                            </Button>
                          )}
                          <Button size="sm" variant="danger" loading={isPending(`del-${version.id}`)} onClick={() => void deleteVersion(version.id)}>
                            Delete
                          </Button>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState title="No versions uploaded yet" />
                )}

                <div className="toolbar">
                  <Input
                    placeholder="Job ID to tailor against"
                    value={tailorJobQuery[resume.id] ?? ""}
                    onChange={(e) => setTailorJobQuery((c) => ({ ...c, [resume.id]: e.target.value }))}
                  />
                  <Button loading={isPending(`tailor-${resume.id}`)} onClick={() => void tailor(resume)}>
                    Generate tailored draft
                  </Button>
                </div>

                {tailorResult[resume.id] && (
                  <div className="prose">
                    <h3 className="card-title">Tailored summary</h3>
                    <p>{tailorResult[resume.id].summary}</p>
                    {tailorResult[resume.id].highlights.length > 0 && (
                      <ul>
                        {tailorResult[resume.id].highlights.map((h, i) => (
                          <li key={i}>{h}</li>
                        ))}
                      </ul>
                    )}
                    {!tailorResult[resume.id].validation.ok && (
                      <p className="inline-error" role="alert">
                        {tailorResult[resume.id].validation.note}
                      </p>
                    )}
                    {tailorResult[resume.id].unsupported_requests.length > 0 && (
                      <>
                        <strong>Could not be supported by evidence</strong>
                        <ul>
                          {tailorResult[resume.id].unsupported_requests.map((u, i) => (
                            <li key={i}>{u}</li>
                          ))}
                        </ul>
                      </>
                    )}
                    <Button loading={isPending(`save-tailor-${resume.id}`)} onClick={() => void saveTailored(resume)}>
                      Save as new version
                    </Button>
                  </div>
                )}
              </Card>
            ))}
          </CardGrid>
        )}
      </AsyncBoundary>
    </>
  );
}
