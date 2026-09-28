"use client";

import { useId, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import type { Suggestion } from "../lib/suggest";
import { SuggestList, useSuggest } from "./Suggest";
import type { SuggestSource } from "./Suggest";

/**
 * Chip editor for the many `string[]` policy fields (roles, keywords, tags).
 *
 * Pass `suggest` (a suggestion kind such as "skill" or "location", or a fixed
 * option list) to get LinkedIn-style type-ahead: suggestions appear while
 * typing, arrow keys move, Enter/Tab picks, and a typed alias resolves to its
 * canonical value ("reactjs" + Enter adds "React").
 */
export function TagInput({
  label,
  values,
  onChange,
  placeholder,
  hint,
  disabled,
  suggest,
}: {
  label?: ReactNode;
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  hint?: ReactNode;
  disabled?: boolean;
  suggest?: SuggestSource;
}) {
  const [draft, setDraft] = useState("");
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;

  function add(parts: string[]) {
    const next = [...values];
    for (const part of parts) {
      if (part && !next.some((v) => v.toLowerCase() === part.toLowerCase())) next.push(part);
    }
    if (next.length !== values.length) onChange(next);
    setDraft("");
  }

  const s = useSuggest({
    source: suggest,
    query: draft,
    exclude: values,
    onPick: (item: Suggestion) => add([item.value]),
  });

  function commitDraft() {
    // Commas let a user paste a whole list in one go.
    const parts = draft
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);
    if (!parts.length) return;
    if (parts.length === 1) {
      const resolved = s.resolveEnter();
      if (resolved) {
        s.pick(resolved);
        return;
      }
    }
    add(parts);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (s.onKeyDown(event)) return;
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commitDraft();
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
      <div className="suggest-anchor">
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
            placeholder={placeholder ?? (suggest ? "Start typing to see suggestions" : "Type and press Enter")}
            disabled={disabled}
            aria-describedby={hintId}
            {...s.inputProps}
            onChange={(event) => {
              setDraft(event.target.value);
              s.setOpen(true);
            }}
            onKeyDown={handleKeyDown}
            onBlur={() => {
              s.setOpen(false);
              commitDraft();
            }}
          />
        </div>
        <SuggestList
          id={s.listId}
          items={s.items}
          active={s.active}
          query={draft}
          visible={s.visible}
          onPick={s.pick}
          onHover={s.setActive}
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
