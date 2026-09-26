"use client";

import type { ReactNode } from "react";
import { Button } from "./Button";

/**
 * Save / Cancel / Reset-to-defaults footer used by every settings form.
 * `dirty` drives whether the destructive-ish actions are even offered.
 */
export function FormActions({
  onSave,
  onCancel,
  onReset,
  saving = false,
  dirty = true,
  saveLabel = "Save changes",
  cancelLabel = "Cancel",
  resetLabel = "Reset to defaults",
  extra,
  note,
}: {
  onSave: () => void;
  onCancel?: () => void;
  onReset?: () => void;
  saving?: boolean;
  dirty?: boolean;
  saveLabel?: string;
  cancelLabel?: string;
  resetLabel?: string;
  extra?: ReactNode;
  note?: ReactNode;
}) {
  return (
    <div className="form-actions">
      <div className="form-actions-left">
        {note && <p className="form-note">{note}</p>}
        {extra}
      </div>
      <div className="form-actions-right">
        {onReset && (
          <Button variant="ghost" onClick={onReset} disabled={saving}>
            {resetLabel}
          </Button>
        )}
        {onCancel && (
          <Button variant="secondary" onClick={onCancel} disabled={saving || !dirty}>
            {cancelLabel}
          </Button>
        )}
        <Button
          variant="primary"
          onClick={onSave}
          loading={saving}
          loadingLabel="Saving…"
          disabled={!dirty}
        >
          {saveLabel}
        </Button>
      </div>
    </div>
  );
}
