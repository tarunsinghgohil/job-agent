import { formatNumber } from "../lib/format";

function scoreTone(score: number, review?: number, high?: number): string {
  // Thresholds come from user preferences; the fallback is only a visual
  // gradient so the bar still renders before preferences have loaded.
  const reviewAt = review ?? 60;
  const highAt = high ?? 85;
  if (score >= highAt) return "high";
  if (score >= reviewAt) return "mid";
  return "low";
}

export function ScoreBar({
  score,
  max = 100,
  label,
  reviewThreshold,
  highThreshold,
  compact = false,
}: {
  score: number;
  max?: number;
  label?: string;
  reviewThreshold?: number;
  highThreshold?: number;
  compact?: boolean;
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (score / max) * 100)) : 0;
  const tone = scoreTone((score / max) * 100, reviewThreshold, highThreshold);
  return (
    <div className={`scorebar ${compact ? "is-compact" : ""}`.trim()}>
      {label && <span className="scorebar-label">{label}</span>}
      <div
        className="scorebar-track"
        role="meter"
        aria-valuenow={Number(score.toFixed(1))}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-label={label ?? "Score"}
      >
        <div className={`scorebar-fill tone-${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="scorebar-value">{formatNumber(score, score % 1 === 0 ? 0 : 1)}</span>
    </div>
  );
}

/** Per-factor breakdown: each factor scored against its configured weight. */
export function ScoreBreakdown({
  breakdown,
  weights,
}: {
  breakdown: Record<string, number>;
  weights?: Record<string, number>;
}) {
  const entries = Object.entries(breakdown);
  if (!entries.length) return <p className="muted">No per-factor breakdown was recorded.</p>;
  return (
    <ul className="breakdown">
      {entries.map(([key, value]) => {
        const max = weights?.[key];
        return (
          <li key={key}>
            <ScoreBar
              score={value}
              max={max && max > 0 ? max : Math.max(value, 1)}
              label={key.replace(/_/g, " ")}
              compact
            />
            {max != null && <span className="breakdown-max">of {max}</span>}
          </li>
        );
      })}
    </ul>
  );
}
