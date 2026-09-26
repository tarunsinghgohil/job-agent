"use client";

import { useId } from "react";
import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

interface FieldShellProps {
  label?: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  children: (id: string, describedBy: string | undefined) => ReactNode;
  className?: string;
}

/** Wires label / hint / error text to the control with real a11y attributes. */
function FieldShell({ label, hint, error, required, children, className = "" }: FieldShellProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={`field ${className}`.trim()}>
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
      {children(id, describedBy)}
      {hint && (
        <p className="field-hint" id={hintId}>
          {hint}
        </p>
      )}
      {error && (
        <p className="field-error" id={errorId} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  wrapperClassName?: string;
}

export function Input({ label, hint, error, wrapperClassName, ...rest }: InputProps) {
  return (
    <FieldShell
      label={label}
      hint={hint}
      error={error}
      required={rest.required}
      className={wrapperClassName}
    >
      {(id, describedBy) => (
        <input
          id={id}
          className="control"
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          {...rest}
        />
      )}
    </FieldShell>
  );
}

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  options: SelectOption[];
  placeholder?: string;
  wrapperClassName?: string;
}

export function Select({
  label,
  hint,
  error,
  options,
  placeholder,
  wrapperClassName,
  ...rest
}: SelectProps) {
  return (
    <FieldShell
      label={label}
      hint={hint}
      error={error}
      required={rest.required}
      className={wrapperClassName}
    >
      {(id, describedBy) => (
        <select
          id={id}
          className="control"
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          {...rest}
        >
          {placeholder !== undefined && <option value="">{placeholder}</option>}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </FieldShell>
  );
}

export interface TextareaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "id"> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  wrapperClassName?: string;
}

export function Textarea({ label, hint, error, wrapperClassName, ...rest }: TextareaProps) {
  return (
    <FieldShell
      label={label}
      hint={hint}
      error={error}
      required={rest.required}
      className={wrapperClassName}
    >
      {(id, describedBy) => (
        <textarea
          id={id}
          className="control control-textarea"
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          {...rest}
        />
      )}
    </FieldShell>
  );
}

export function FieldRow({ children, columns = 2 }: { children: ReactNode; columns?: 1 | 2 | 3 }) {
  return <div className={`field-row cols-${columns}`}>{children}</div>;
}
