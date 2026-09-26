import Link from "next/link";
import type { ReactNode } from "react";

export function StatTile({
  label,
  value,
  hint,
  href,
  tone = "neutral",
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  href?: string;
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
}) {
  const body = (
    <>
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {hint && <span className="stat-hint">{hint}</span>}
    </>
  );
  if (href) {
    return (
      <Link className={`stat-tile tone-${tone} is-link`} href={href}>
        {body}
      </Link>
    );
  }
  return <div className={`stat-tile tone-${tone}`}>{body}</div>;
}

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="stat-grid">{children}</div>;
}

/** Used vs remaining meter, e.g. the daily application cap or AI budget. */
export function UsageMeter({
  label,
  used,
  total,
  unit = "",
  formatValue,
}: {
  label: string;
  used: number;
  total: number;
  unit?: string;
  formatValue?: (value: number) => string;
}) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const remaining = Math.max(0, total - used);
  const fmt = formatValue ?? ((value: number) => `${value}${unit}`);
  const tone = pct >= 100 ? "low" : pct >= 80 ? "mid" : "high";
  return (
    <div className="usage-meter">
      <div className="usage-head">
        <span>{label}</span>
        <span className="usage-numbers">
          {fmt(used)} / {fmt(total)}
        </span>
      </div>
      <div
        className="scorebar-track"
        role="meter"
        aria-valuenow={used}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label={label}
      >
        <div className={`scorebar-fill tone-${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="usage-foot">{fmt(remaining)} remaining</p>
    </div>
  );
}
