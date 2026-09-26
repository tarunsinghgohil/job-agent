"use client";

import { useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { FieldRow, Input, Textarea } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { titleize } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import type { AnswerBankEntry, ResolvedAnswer } from "../../lib/types";

const STATE_TONE: Record<string, "success" | "warning" | "danger"> = {
  verified: "success",
  inferred: "warning",
  needs_review: "danger",
};

const EMPTY_FORM = { question: "", answer: "", category: "general", company_normalized: "" };

export function AnswersView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const [form, setForm] = useState(EMPTY_FORM);
  const [draftQuestion, setDraftQuestion] = useState("");
  const [draftResult, setDraftResult] = useState<ResolvedAnswer | null>(null);

  const answers = useResource<AnswerBankEntry[]>((signal) => api.get<AnswerBankEntry[]>("/api/v1/answers", undefined, signal));

  async function save() {
    if (!form.question.trim() || !form.answer.trim()) {
      toast.error("Question and answer are both required.");
      return;
    }
    await run("save", async () => {
      const ok = await toast.withToast(() => api.post("/api/v1/answers", form), "Answer saved.", "Could not save");
      if (ok !== undefined) {
        setForm(EMPTY_FORM);
        answers.reload();
      }
    });
  }

  async function remove(id: string) {
    await run(`del-${id}`, async () => {
      await toast.withToast(() => api.del(`/api/v1/answers/${id}`), "Answer removed.");
      answers.reload();
    });
  }

  async function draftWithAi() {
    if (!draftQuestion.trim()) {
      toast.error("Enter a question to draft.");
      return;
    }
    await run("draft", async () => {
      const result = await toast.withToast(
        () => api.post<ResolvedAnswer>("/api/v1/answers/draft", { question: draftQuestion }),
        "Draft ready — review before saving.",
        "AI drafting failed",
      );
      if (result) setDraftResult(result);
    });
  }

  function useDraft() {
    if (!draftResult) return;
    setForm({ question: draftResult.question, answer: draftResult.answer, category: "general", company_normalized: "" });
    setDraftResult(null);
    setDraftQuestion("");
  }

  const grouped = (answers.data ?? []).reduce<Record<string, AnswerBankEntry[]>>((acc, entry) => {
    (acc[entry.category] ??= []).push(entry);
    return acc;
  }, {});

  return (
    <>
      <PageHeader title="Answer bank" description="Reusable application answers. AI drafts are grounded and need review." />

      <Card title="Add an answer">
        <FieldRow>
          <Input label="Question" value={form.question} onChange={(e) => setForm((f) => ({ ...f, question: e.target.value }))} />
          <Input label="Category" value={form.category} onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))} />
        </FieldRow>
        <Textarea label="Answer" rows={3} value={form.answer} onChange={(e) => setForm((f) => ({ ...f, answer: e.target.value }))} />
        <Input
          label="Company override (optional)"
          hint="Only applies when the application's company matches this."
          value={form.company_normalized}
          onChange={(e) => setForm((f) => ({ ...f, company_normalized: e.target.value }))}
        />
        <Button variant="primary" loading={isPending("save")} onClick={() => void save()}>
          Save answer
        </Button>
      </Card>

      <Card title="Draft with AI" description="Grounded in your profile and existing answers.">
        <FieldRow>
          <Input label="Question to draft" value={draftQuestion} onChange={(e) => setDraftQuestion(e.target.value)} />
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <Button loading={isPending("draft")} onClick={() => void draftWithAi()}>
              Draft
            </Button>
          </div>
        </FieldRow>
        {draftResult && (
          <div className="prose">
            <p>{draftResult.answer}</p>
            <Badge tone={STATE_TONE[draftResult.state] ?? "warning"}>{titleize(draftResult.state)}</Badge>
            <div>
              <Button size="sm" onClick={useDraft}>
                Use this draft
              </Button>
            </div>
          </div>
        )}
      </Card>

      <AsyncBoundary
        loading={answers.loading}
        error={answers.error}
        data={answers.data}
        onRetry={answers.reload}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="No answers yet" />}
      >
        {() =>
          Object.entries(grouped).map(([category, entries]) => (
            <Card key={category} title={<span className="group-heading">{titleize(category)} <span className="group-count">{entries.length}</span></span>}>
              <ul className="list-rows">
                {entries.map((entry) => (
                  <li className="list-row" key={entry.id}>
                    <div className="list-row-main">
                      <strong>{entry.question}</strong>
                      <span>{entry.answer}</span>
                      {entry.company_normalized && <span className="muted">Only for: {entry.company_normalized}</span>}
                    </div>
                    <Badge tone={STATE_TONE[entry.state] ?? "warning"}>{titleize(entry.state)}</Badge>
                    <Button size="sm" variant="danger" loading={isPending(`del-${entry.id}`)} onClick={() => void remove(entry.id)}>
                      Delete
                    </Button>
                  </li>
                ))}
              </ul>
            </Card>
          ))
        }
      </AsyncBoundary>
    </>
  );
}
