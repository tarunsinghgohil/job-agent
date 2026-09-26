/**
 * Minimal inline-SVG charts. Deliberately dependency-free: the project must not
 * gain a charting library. Each chart also renders an accessible text summary.
 */
import { formatNumber } from "../lib/format";

export interface SeriesPoint {
  label: string;
  value: number;
}

export function LineChart({
  points,
  title,
  height = 160,
  valueSuffix = "",
}: {
  points: SeriesPoint[];
  title: string;
  height?: number;
  valueSuffix?: string;
}) {
  if (!points.length) return <p className="muted">No data for this period.</p>;

  const width = 640;
  const padding = { top: 12, right: 12, bottom: 24, left: 36 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const max = Math.max(...points.map((p) => p.value), 1);
  const stepX = points.length > 1 ? innerW / (points.length - 1) : 0;

  const coords = points.map((point, index) => ({
    x: padding.left + index * stepX,
    y: padding.top + innerH - (point.value / max) * innerH,
    point,
  }));
  const path = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const area = `${path} L${coords[coords.length - 1].x.toFixed(1)},${(padding.top + innerH).toFixed(
    1,
  )} L${coords[0].x.toFixed(1)},${(padding.top + innerH).toFixed(1)} Z`;

  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${title}. Peak ${formatNumber(max)}${valueSuffix}.`}
        preserveAspectRatio="none"
        className="chart-svg"
      >
        <line
          x1={padding.left}
          y1={padding.top + innerH}
          x2={width - padding.right}
          y2={padding.top + innerH}
          className="chart-axis"
        />
        <text x={4} y={padding.top + 10} className="chart-tick">
          {formatNumber(max)}
        </text>
        <text x={4} y={padding.top + innerH} className="chart-tick">
          0
        </text>
        <path d={area} className="chart-area" />
        <path d={path} className="chart-line" />
        {coords.map((c) => (
          <circle key={c.point.label} cx={c.x} cy={c.y} r={2.5} className="chart-dot">
            <title>{`${c.point.label}: ${formatNumber(c.point.value)}${valueSuffix}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="chart-caption">
        {points[0].label} → {points[points.length - 1].label}
      </figcaption>
    </figure>
  );
}

export function BarChart({
  points,
  title,
  horizontal = false,
  valueSuffix = "",
}: {
  points: SeriesPoint[];
  title: string;
  horizontal?: boolean;
  valueSuffix?: string;
}) {
  if (!points.length) return <p className="muted">No data for this period.</p>;
  const max = Math.max(...points.map((p) => p.value), 1);

  if (horizontal) {
    return (
      <ul className="hbar" aria-label={title}>
        {points.map((point) => (
          <li key={point.label}>
            <span className="hbar-label">{point.label}</span>
            <span className="hbar-track">
              <span
                className="hbar-fill"
                style={{ width: `${(point.value / max) * 100}%` }}
                aria-hidden="true"
              />
            </span>
            <span className="hbar-value">
              {formatNumber(point.value)}
              {valueSuffix}
            </span>
          </li>
        ))}
      </ul>
    );
  }

  const width = 640;
  const height = 180;
  const padding = { top: 12, right: 12, bottom: 32, left: 36 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const slot = innerW / points.length;
  const barW = Math.max(6, slot * 0.6);

  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${title}. ${points.map((p) => `${p.label} ${p.value}`).join(", ")}.`}
        className="chart-svg"
      >
        <line
          x1={padding.left}
          y1={padding.top + innerH}
          x2={width - padding.right}
          y2={padding.top + innerH}
          className="chart-axis"
        />
        {points.map((point, index) => {
          const barH = (point.value / max) * innerH;
          const x = padding.left + index * slot + (slot - barW) / 2;
          const y = padding.top + innerH - barH;
          return (
            <g key={point.label}>
              <rect x={x} y={y} width={barW} height={Math.max(barH, 1)} className="chart-bar" rx={3}>
                <title>{`${point.label}: ${formatNumber(point.value)}${valueSuffix}`}</title>
              </rect>
              <text x={x + barW / 2} y={height - 10} className="chart-tick" textAnchor="middle">
                {point.label}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

export function Funnel({ stages }: { stages: SeriesPoint[] }) {
  if (!stages.length) return <p className="muted">No funnel data yet.</p>;
  const max = Math.max(...stages.map((s) => s.value), 1);
  return (
    <ol className="funnel">
      {stages.map((stage, index) => {
        const previous = index > 0 ? stages[index - 1].value : null;
        const conversion = previous && previous > 0 ? (stage.value / previous) * 100 : null;
        return (
          <li key={stage.label}>
            <div className="funnel-head">
              <span>{stage.label}</span>
              <strong>{formatNumber(stage.value)}</strong>
            </div>
            <div className="funnel-track">
              <div
                className="funnel-fill"
                style={{ width: `${(stage.value / max) * 100}%` }}
                aria-hidden="true"
              />
            </div>
            {conversion !== null && (
              <p className="funnel-conv">{conversion.toFixed(0)}% of previous stage</p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
