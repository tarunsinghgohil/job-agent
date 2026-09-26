"use client";

import { useId, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

/** Chip editor for the many `string[]` policy fields (roles, keywords, tags). */
export function TagInput({
  label,
  values,
  onChange,
  placeholder = "Type and press Enter",
  hint,
  disabled,
}: {
  label?: ReactNode;
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;

  function commit(raw: string) {
    // Commas let a user paste a whole list in one go.
    const parts = raw
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);
    if (!parts.length) return;
    const next = [...values];
    for (const part of parts) {
      if (!next.some((v) => v.toLowerCase() === part.toLowerCase())) next.push(part);
    }
    onChange(next);
    setDraft("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commit(draft);
    } else if (event.key === "Backspace" && draft === "" && values.length) {
      onChange(values.slice(0, -1));
    }
  }

  return (
    <div className="field">
      {label && (
        <label className="field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <div className={`taginput ${disabled ? "is-disabled" : ""}`.trim()}>
        <ul className="taginput-chips">
          {values.map((value) => (
            <li key={value} className="chip">
              <span>{value}</span>
              <button
                type="button"
                className="chip-remove"
                aria-label={`Remove ${value}`}
                disabled={disabled}
                onClick={() => onChange(values.filter((v) => v !== value))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        <input
          id={id}
          className="taginput-input"
          value={draft}
          placeholder={placeholder}
          disabled={disabled}
          aria-describedby={hintId}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={() => commit(draft)}
        />
      </div>
      {hint && (
        <p className="field-hint" id={hintId}>
          {hint}
        </p>
      )}
    </div>
  );
}
