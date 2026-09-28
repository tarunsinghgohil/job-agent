"use client";

import { useId } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { SuggestList, useSuggest } from "./Suggest";
import type { SuggestSource } from "./Suggest";

/**
 * A single-value text field with type-ahead suggestions (location, title,
 * company...). Free text is always allowed; suggestions only help.
 */
export function SuggestInput({
  label,
  value,
  onChange,
  suggest,
  placeholder,
  hint,
  required,
  disabled,
}: {
  label?: ReactNode;
  value: string;
  onChange: (next: string) => void;
  suggest: SuggestSource;
  placeholder?: string;
  hint?: ReactNode;
  required?: boolean;
  disabled?: boolean;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const s = useSuggest({
    source: suggest,
    query: value,
    onPick: (item) => {
      onChange(item.value);
      s.setOpen(false);
    },
  });

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (s.onKeyDown(event)) return;
    if (event.key === "Enter" && s.visible) {
      const resolved = s.resolveEnter();
      if (resolved) {
        // Only swallow Enter when it picked something; otherwise let forms submit.
        event.preventDefault();
        s.pick(resolved);
      }
    }
  }

  return (
    <div className="field">
      {label && (
        <label className="field-label" htmlFor={id}>
          {label}
          {required && (
            <span className="field-required" aria-hidden="true">
              *
            </span>
          )}
        </label>
      )}
      <div className="suggest-anchor">
        <input
          id={id}
          className="control"
          value={value}
          placeholder={placeholder}
          required={required}
          disabled={disabled}
          aria-describedby={hintId}
          {...s.inputProps}
          onChange={(event) => {
            onChange(event.target.value);
            s.setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          onBlur={() => s.setOpen(false)}
        />
        <SuggestList
          id={s.listId}
          items={s.items}
          active={s.active}
          query={value}
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
