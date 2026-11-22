import { formatPercent } from "../../legacy/formatters.js";

import type { TrendPoint } from "../types";

type TrendChartProps = {
  points: TrendPoint[];
};

export function TrendChart({ points }: TrendChartProps) {
  if (!points.length) {
    return <p className="trend-chart-empty">No trend points yet.</p>;
  }

  const width = 640;
  const height = 220;
  const padding = { top: 20, right: 20, bottom: 36, left: 48 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const rates = points.flatMap((point) => [
    Number(point.baseline_fallback_rate || 0),
    Number(point.candidate_fallback_rate || 0),
  ]);
  const maxRate = Math.max(0.01, ...rates);
  const ticks = [0, maxRate / 2, maxRate];

  const xForIndex = (index: number) => {
    if (points.length === 1) {
      return padding.left + plotWidth / 2;
    }
    return padding.left + (plotWidth * index) / (points.length - 1);
  };

  const yForRate = (rate: number) =>
    padding.top + plotHeight - (Math.max(0, rate) / maxRate) * plotHeight;

  const buildPath = (key: "candidate_fallback_rate" | "baseline_fallback_rate") =>
    points
      .map((point, index) => {
        const command = index === 0 ? "M" : "L";
        return `${command}${xForIndex(index).toFixed(2)} ${yForRate(Number(point[key] || 0)).toFixed(2)}`;
      })
      .join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="trend-chart-svg"
      role="img"
      aria-label="Candidate and baseline fallback-rate trend lines across recent evaluations"
    >
      {ticks.map((tick) => {
        const y = yForRate(tick);
        return (
          <g key={`tick-${tick}`}>
            <line
              x1={padding.left}
              y1={y}
              x2={width - padding.right}
              y2={y}
              className="trend-grid-line"
            />
            <text x={padding.left - 10} y={y + 4} textAnchor="end" className="trend-axis-label">
              {formatPercent(tick)}
            </text>
          </g>
        );
      })}

      <line
        x1={padding.left}
        y1={height - padding.bottom}
        x2={width - padding.right}
        y2={height - padding.bottom}
        className="trend-axis-line"
      />
      <line
        x1={padding.left}
        y1={padding.top}
        x2={padding.left}
        y2={height - padding.bottom}
        className="trend-axis-line"
      />

      <path d={buildPath("candidate_fallback_rate")} className="trend-line trend-line-candidate" />
      <path d={buildPath("baseline_fallback_rate")} className="trend-line trend-line-baseline" />

      {points.map((point, index) => {
        const x = xForIndex(index);
        const y = yForRate(Number(point.candidate_fallback_rate || 0));
        return (
          <circle
            key={`candidate-${point.evaluation_id}`}
            cx={x}
            cy={y}
            r={4}
            className="trend-dot trend-dot-candidate"
          >
            <title>
              Evaluation #{point.evaluation_id}: candidate {formatPercent(point.candidate_fallback_rate)}
            </title>
          </circle>
        );
      })}

      {points.map((point, index) => {
        const x = xForIndex(index);
        const y = yForRate(Number(point.baseline_fallback_rate || 0));
        return (
          <circle
            key={`baseline-${point.evaluation_id}`}
            cx={x}
            cy={y}
            r={4}
            className="trend-dot trend-dot-baseline"
          >
            <title>
              Evaluation #{point.evaluation_id}: baseline {formatPercent(point.baseline_fallback_rate)}
            </title>
          </circle>
        );
      })}

      {points.map((point, index) => (
        <text
          key={`xlabel-${point.evaluation_id}`}
          x={xForIndex(index)}
          y={height - 12}
          textAnchor="middle"
          className="trend-axis-label"
        >
          #{point.evaluation_id}
        </text>
      ))}
    </svg>
  );
}
