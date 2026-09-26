import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "success" | "warning" | "danger" | "info" | "accent";

const DECISION_TONES: Record<string, BadgeTone> = {
  HIGH_PRIORITY: "success",
  REVIEW: "warning",
  REJECT: "danger",
};

const STATUS_TONES: Record<string, BadgeTone> = {
  healthy: "success",
  success: "success",
  verified: "success",
  sent: "success",
  approved: "info",
  prepared: "info",
  submitted: "info",
  interview: "accent",
  offer: "success",
  running: "info",
  partial: "warning",
  degraded: "warning",
  pending: "warning",
  pending_review: "warning",
  needs_review: "warning",
  inferred: "warning",
  qualified: "success",
  queued: "info",
  applied: "info",
  new: "accent",
  failing: "danger",
  failed: "danger",
  rejected: "danger",
  withdrawn: "neutral",
  cancelled: "neutral",
  closed: "neutral",
  archived: "neutral",
  disabled: "neutral",
  suppressed: "neutral",
  unknown: "neutral",
};

/** Maps a backend status/decision string onto a visual tone. */
export function toneFor(value: string | null | undefined): BadgeTone {
  if (!value) return "neutral";
  return DECISION_TONES[value] ?? STATUS_TONES[value.toLowerCase()] ?? "neutral";
}

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  title?: string;
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

/** Convenience wrapper that derives its tone from the value itself. */
export function StatusBadge({ value, label }: { value: string | null | undefined; label?: string }) {
  const text = label ?? (value ? value.replace(/_/g, " ").toLowerCase() : "unknown");
  return <Badge tone={toneFor(value)}>{text}</Badge>;
}
