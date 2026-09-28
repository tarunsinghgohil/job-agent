import type { BadgeTone } from "../../components/Badge";
import type { HuntItem, HuntWeightKey } from "../../lib/types";

export const STRENGTH_LABEL: Record<HuntItem["strength"], string> = {
  strong: "Strong match",
  good: "Good match",
  partial: "Partial match",
  weak: "Weak match",
  none: "Not a match",
};

export const STRENGTH_TONE: Record<HuntItem["strength"], BadgeTone> = {
  strong: "success",
  good: "info",
  partial: "warning",
  weak: "neutral",
  none: "danger",
};

export const EXPERIENCE_LABEL: Record<HuntItem["experience_fit"], string> = {
  strong: "strong fit",
  good: "close fit",
  stretch: "stretch",
  under: "below your level",
  unknown: "not stated",
};

export const EXPERIENCE_TONE: Record<HuntItem["experience_fit"], BadgeTone> = {
  strong: "success",
  good: "info",
  stretch: "warning",
  under: "danger",
  unknown: "neutral",
};

export const WORK_MODE_LABEL: Record<string, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  onsite: "On-site",
  unknown: "Mode unknown",
};

export function applyLinkText(item: Pick<HuntItem, "apply_link_type" | "apply_link_label">): {
  text: string;
  tone: BadgeTone;
  title: string;
} {
  switch (item.apply_link_type) {
    case "ats":
      return {
        text: `Direct · ${item.apply_link_label}`,
        tone: "success",
        title: "Links straight to the employer's applicant tracking system",
      };
    case "company":
      return {
        text: "Company site",
        tone: "info",
        title: `Links to ${item.apply_link_label || "the employer's own site"}`,
      };
    case "aggregator":
      return {
        text: `Via ${item.apply_link_label || "job board"}`,
        tone: "warning",
        title: "Links to a job board copy; look for the employer's own posting before applying",
      };
    case "email":
      return { text: "Apply by email", tone: "info", title: "The posting publishes an application address" };
    default:
      return { text: "No apply link", tone: "neutral", title: "The source did not include an application link" };
  }
}

export function experienceRange(min: number | null, max: number | null): string {
  if (min != null && max != null) return min === max ? `${min} yrs` : `${min}–${max} yrs`;
  if (min != null) return `${min}+ yrs`;
  if (max != null) return `up to ${max} yrs`;
  return "Experience not stated";
}

export const WEIGHT_LABELS: Record<HuntWeightKey, { label: string; hint: string }> = {
  location: { label: "Location priority", hint: "Higher tiers score more" },
  role: { label: "Role / title", hint: "Title matches a target role" },
  skills: { label: "Skill overlap", hint: "Share of the job's skills you have" },
  experience: { label: "Experience", hint: "Fit against your years" },
  freshness: { label: "Freshness", hint: "Newer postings score more" },
  semantic: { label: "Semantic similarity", hint: "Resume vs description" },
  apply_link: { label: "Apply link quality", hint: "Direct ATS beats job boards" },
};

export const WEIGHT_KEYS = Object.keys(WEIGHT_LABELS) as HuntWeightKey[];

export const CRON_PRESETS = [
  { value: "0 2,8,14,20 * * *", label: "Every 6 hours (2am, 8am, 2pm, 8pm)" },
  { value: "0 8,20 * * *", label: "Twice a day (8am, 8pm)" },
  { value: "0 8 * * *", label: "Daily at 8am" },
  { value: "0 9 * * 1-5", label: "Weekdays at 9am" },
];
