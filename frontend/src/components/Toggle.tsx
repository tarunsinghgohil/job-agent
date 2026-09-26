"use client";

import { useId } from "react";
import type { ReactNode } from "react";

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
  name,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  name?: string;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className="toggle-row">
      <button
        type="button"
        id={id}
        name={name}
        role="switch"
        aria-checked={checked}
        aria-describedby={hintId}
        className={`toggle ${checked ? "is-on" : ""}`.trim()}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      >
        <span className="toggle-knob" />
      </button>
      <div className="toggle-text">
        <label htmlFor={id} className="toggle-label">
          {label}
        </label>
        {hint && (
          <p className="field-hint" id={hintId}>
            {hint}
          </p>
        )}
      </div>
    </div>
  );
}
