import type { ServiceCheck } from "../api/client";

type ResponseTimeChartProps = {
  checks: ServiceCheck[];
};

const WIDTH = 720;
const HEIGHT = 220;
const PADDING = { top: 16, right: 18, bottom: 32, left: 48 };

export function ResponseTimeChart({ checks }: ResponseTimeChartProps) {
  const samples = checks
    .filter((check) => check.response_time_ms !== null)
    .slice()
    .sort((a, b) => Date.parse(a.checked_at) - Date.parse(b.checked_at));

  if (samples.length === 0) {
    return <div className="chart-empty">Response-time history will appear after the first real service check.</div>;
  }

  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;
  const maxValue = Math.max(100, ...samples.map((sample) => sample.response_time_ms ?? 0));
  const points = samples.map((sample, index) => {
    const x = PADDING.left + (samples.length === 1 ? plotWidth / 2 : (index / (samples.length - 1)) * plotWidth);
    const y = PADDING.top + plotHeight - ((sample.response_time_ms ?? 0) / maxValue) * plotHeight;
    return { x, y, sample };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area = `${PADDING.left},${HEIGHT - PADDING.bottom} ${line} ${WIDTH - PADDING.right},${HEIGHT - PADDING.bottom}`;

  return (
    <div className="chart-wrap">
      <svg className="response-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Service response time history">
        <defs>
          <linearGradient id="response-stroke" x1="0" x2="1" y1="0" y2="0"><stop offset="0%" stopColor="#6f5adc" /><stop offset="100%" stopColor="#9ff0ec" /></linearGradient>
          <linearGradient id="response-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#6f5adc" stopOpacity=".2" /><stop offset="100%" stopColor="#9ff0ec" stopOpacity="0" /></linearGradient>
        </defs>
        {[0, 0.5, 1].map((fraction) => {
          const y = PADDING.top + plotHeight * fraction;
          const label = Math.round(maxValue * (1 - fraction));
          return (
            <g key={fraction}>
              <line x1={PADDING.left} x2={WIDTH - PADDING.right} y1={y} y2={y} className="chart-grid" />
              <text x={PADDING.left - 10} y={y + 4} textAnchor="end" className="chart-label">{label} ms</text>
            </g>
          );
        })}
        <polygon points={area} className="chart-area" />
        <polyline points={line} className="chart-line" />
        {points.map((point) => (
          <circle
            key={point.sample.id}
            cx={point.x}
            cy={point.y}
            r="3.5"
            className={point.sample.is_available ? "chart-dot" : "chart-dot chart-dot-failed"}
          >
            <title>{`${point.sample.response_time_ms} ms · ${new Date(point.sample.checked_at).toLocaleString()}`}</title>
          </circle>
        ))}
      </svg>
      <div className="chart-axis-labels">
        <span>{new Date(samples[0].checked_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
        <span>{new Date(samples[samples.length - 1].checked_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
      </div>
    </div>
  );
}
