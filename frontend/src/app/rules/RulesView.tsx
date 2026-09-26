"use client";

import { useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { FieldRow, Input, Select, Textarea } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { Toggle } from "../../components/Toggle";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { titleize } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import { RULE_FIELDS, RULE_OPERATORS } from "../../lib/types";
import type { MatchRule, RuleTestResult } from "../../lib/types";

const FIELD_OPTIONS = RULE_FIELDS.map((f) => ({ value: f, label: titleize(f) }));
const OPERATOR_OPTIONS = RULE_OPERATORS.map((o) => ({ value: o, label: titleize(o) }));

interface DraftRule {
  name: string;
  field: string;
  operator: string;
  valueText: string;
  weight: number;
  is_hard: boolean;
  enabled: boolean;
  priority: number;
  explanation: string;
  case_sensitive: boolean;
}

const EMPTY_DRAFT: DraftRule = {
  name: "",
  field: "description",
  operator: "contains",
  valueText: "",
  weight: 5,
  is_hard: false,
  enabled: true,
  priority: 100,
  explanation: "",
  case_sensitive: false,
};

function parseValue(text: string): string | number | string[] {
  const parts = text.split(",").map((p) => p.trim()).filter(Boolean);
  if (parts.length <= 1) return text.trim();
  return parts;
}

export function RulesView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const [draft, setDraft] = useState<DraftRule>(EMPTY_DRAFT);
  const [testJobId, setTestJobId] = useState<Record<string, string>>({});
  const [testResults, setTestResults] = useState<Record<string, RuleTestResult>>({});

  const rules = useResource<MatchRule[]>((signal) => api.get<MatchRule[]>("/api/v1/rules", undefined, signal));

  async function create() {
    if (!draft.name.trim()) {
      toast.error("Give the rule a name.");
      return;
    }
    await run("create", async () => {
      const ok = await toast.withToast(
        () =>
          api.post("/api/v1/rules", {
            name: draft.name,
            field: draft.field,
            operator: draft.operator,
            value: parseValue(draft.valueText),
            weight: draft.weight,
            is_hard: draft.is_hard,
            enabled: draft.enabled,
            priority: draft.priority,
            explanation: draft.explanation,
            case_sensitive: draft.case_sensitive,
          }),
        "Rule created.",
        "Could not create the rule",
      );
      if (ok !== undefined) {
        setDraft(EMPTY_DRAFT);
        rules.reload();
      }
    });
  }

  async function toggleEnabled(rule: MatchRule) {
    await run(`toggle-${rule.id}`, async () => {
      await toast.withToast(() => api.put(`/api/v1/rules/${rule.id}`, { ...rule, enabled: !rule.enabled }), "Updated.");
      rules.reload();
    });
  }

  async function remove(id: string) {
    await run(`del-${id}`, async () => {
      await toast.withToast(() => api.del(`/api/v1/rules/${id}`), "Rule deleted. Re-score jobs to apply.");
      rules.reload();
    });
  }

  async function testRule(rule: MatchRule) {
    const jobId = testJobId[rule.id]?.trim();
    if (!jobId) {
      toast.error("Enter a job ID to test against.");
      return;
    }
    await run(`test-${rule.id}`, async () => {
      const result = await toast.withToast(
        () => api.post<RuleTestResult>(`/api/v1/rules/${rule.id}/test`, { job_id: jobId }),
        "Test complete.",
        "Test failed",
      );
      if (result) setTestResults((current) => ({ ...current, [rule.id]: result }));
    });
  }

  return (
    <>
      <PageHeader title="Match rules" description="Dynamic rules the matching engine evaluates alongside your preferences." />

      <Card title="Add a rule">
        <FieldRow>
          <Input label="Name" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
          <Input
            label="Priority"
            type="number"
            value={draft.priority}
            onChange={(e) => setDraft((d) => ({ ...d, priority: Number(e.target.value) || 0 }))}
          />
        </FieldRow>
        <FieldRow columns={3}>
          <Select label="Field" options={FIELD_OPTIONS} value={draft.field} onChange={(e) => setDraft((d) => ({ ...d, field: e.target.value }))} />
          <Select
            label="Operator"
            options={OPERATOR_OPTIONS}
            value={draft.operator}
            onChange={(e) => setDraft((d) => ({ ...d, operator: e.target.value }))}
          />
          <Input
            label="Value(s)"
            hint="Comma-separated for multiple"
            value={draft.valueText}
            onChange={(e) => setDraft((d) => ({ ...d, valueText: e.target.value }))}
          />
        </FieldRow>
        <FieldRow>
          <Toggle label="Hard requirement" hint="A failure rejects the job outright." checked={draft.is_hard} onChange={(v) => setDraft((d) => ({ ...d, is_hard: v }))} />
          {!draft.is_hard && (
            <Input
              label="Weight"
              type="number"
              value={draft.weight}
              onChange={(e) => setDraft((d) => ({ ...d, weight: Number(e.target.value) || 0 }))}
            />
          )}
        </FieldRow>
        <Textarea
          label="Explanation"
          hint="Shown to you when this rule causes a rejection."
          value={draft.explanation}
          onChange={(e) => setDraft((d) => ({ ...d, explanation: e.target.value }))}
        />
        <Button variant="primary" loading={isPending("create")} onClick={() => void create()}>
          Create rule
        </Button>
      </Card>

      <AsyncBoundary
        loading={rules.loading}
        error={rules.error}
        data={rules.data}
        onRetry={rules.reload}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="No custom rules yet" description="Deterministic preferences already apply; rules add extra checks." />}
      >
        {(items) => (
          <Card title="Rules">
            <ul className="list-rows">
              {items
                .slice()
                .sort((a, b) => a.priority - b.priority)
                .map((rule) => (
                  <li className="list-row" key={rule.id}>
                    <div className="list-row-main">
                      <strong>
                        {rule.name} {rule.is_hard ? <Badge tone="danger">Hard</Badge> : <Badge tone="info">+{rule.weight}</Badge>}
                        {!rule.enabled && <Badge tone="neutral">Disabled</Badge>}
                      </strong>
                      <span>
                        {titleize(rule.field)} {titleize(rule.operator)} {JSON.stringify(rule.value)}
                      </span>
                      {rule.explanation && <span className="muted">{rule.explanation}</span>}
                      <div className="toolbar">
                        <Input
                          placeholder="Job ID to test"
                          value={testJobId[rule.id] ?? ""}
                          onChange={(e) => setTestJobId((c) => ({ ...c, [rule.id]: e.target.value }))}
                        />
                        <Button size="sm" loading={isPending(`test-${rule.id}`)} onClick={() => void testRule(rule)}>
                          Test
                        </Button>
                      </div>
                      {testResults[rule.id] && (
                        <p className={testResults[rule.id].passed ? "muted" : "inline-error"}>
                          {testResults[rule.id].passed ? "Passed" : "Failed"}: {testResults[rule.id].detail}
                        </p>
                      )}
                    </div>
                    <div className="list-row-actions">
                      <Button size="sm" variant="ghost" loading={isPending(`toggle-${rule.id}`)} onClick={() => void toggleEnabled(rule)}>
                        {rule.enabled ? "Disable" : "Enable"}
                      </Button>
                      <Button size="sm" variant="danger" loading={isPending(`del-${rule.id}`)} onClick={() => void remove(rule.id)}>
                        Delete
                      </Button>
                    </div>
                  </li>
                ))}
            </ul>
          </Card>
        )}
      </AsyncBoundary>
    </>
  );
}
