"use client";

import { Button } from "../../components/Button";
import { Input, Select } from "../../components/Field";
import { TagInput } from "../../components/TagInput";
import { HUNT_WORK_MODES } from "../../lib/types";
import type { HuntTier, HuntWorkMode } from "../../lib/types";
import { WORK_MODE_LABEL } from "./huntFormat";

const KIND_OPTIONS = [
  { value: "apply_first", label: "Apply first" },
  { value: "review", label: "Worth reviewing" },
];

function blankTier(country: string): HuntTier {
  return { name: "", group: "", work_modes: ["onsite", "hybrid"], places: [country || "India"], kind: "review" };
}

export function TierEditor({
  tiers,
  country,
  onChange,
}: {
  tiers: HuntTier[];
  country: string;
  onChange: (next: HuntTier[]) => void;
}) {
  function update(index: number, patch: Partial<HuntTier>) {
    onChange(tiers.map((tier, i) => (i === index ? { ...tier, ...patch } : tier)));
  }

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= tiers.length) return;
    const next = [...tiers];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  function toggleMode(index: number, mode: HuntWorkMode) {
    const current = tiers[index].work_modes;
    const next = current.includes(mode) ? current.filter((m) => m !== mode) : [...current, mode];
    // At least one mode must stay selected; the API rejects an empty list.
    if (next.length) update(index, { work_modes: HUNT_WORK_MODES.filter((m) => next.includes(m)) });
  }

  return (
    <div className="tier-editor">
      <ol className="tier-list">
        {tiers.map((tier, index) => (
          <li key={index} className="tier-row">
            <div className="tier-rank" aria-hidden="true">
              {index + 1}
            </div>
            <div className="tier-fields">
              <div className="tier-line">
                <Input
                  label="Name"
                  value={tier.name}
                  placeholder="e.g. Remote India"
                  onChange={(e) => update(index, { name: e.target.value })}
                  required
                />
                <Input
                  label="Shortlist section"
                  hint="Tiers with the same section share one heading"
                  value={tier.group}
                  placeholder={tier.name || "Section"}
                  onChange={(e) => update(index, { group: e.target.value })}
                />
                <Select
                  label="Bucket"
                  options={KIND_OPTIONS}
                  value={tier.kind}
                  onChange={(e) => update(index, { kind: e.target.value as HuntTier["kind"] })}
                />
              </div>
              <div className="tier-line">
                <fieldset className="tier-modes">
                  <legend className="field-label">Work mode</legend>
                  {HUNT_WORK_MODES.map((mode) => (
                    <label key={mode} className={`mode-pill ${tier.work_modes.includes(mode) ? "is-on" : ""}`}>
                      <input
                        type="checkbox"
                        checked={tier.work_modes.includes(mode)}
                        onChange={() => toggleMode(index, mode)}
                      />
                      {WORK_MODE_LABEL[mode]}
                    </label>
                  ))}
                </fieldset>
                <div className="tier-places">
                  <TagInput
                    label="Places"
                    suggest="location"
                    values={tier.places}
                    onChange={(places) => update(index, { places })}
                    placeholder="City, state or country"
                    hint={
                      tier.work_modes.includes("remote")
                        ? `For remote, "${country}" means open to candidates in ${country}.`
                        : `"${country}" means anywhere in ${country}.`
                    }
                  />
                </div>
              </div>
            </div>
            <div className="tier-actions">
              <Button size="sm" variant="ghost" aria-label={`Move ${tier.name || "tier"} up`} disabled={index === 0} onClick={() => move(index, -1)}>
                ↑
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Move ${tier.name || "tier"} down`}
                disabled={index === tiers.length - 1}
                onClick={() => move(index, 1)}
              >
                ↓
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Remove ${tier.name || "tier"}`}
                disabled={tiers.length === 1}
                onClick={() => onChange(tiers.filter((_, i) => i !== index))}
              >
                ✕
              </Button>
            </div>
          </li>
        ))}
      </ol>
      <Button size="sm" onClick={() => onChange([...tiers, blankTier(country)])}>
        Add location priority
      </Button>
    </div>
  );
}
