// Tiny inline SVG sparkline — no chart library. Draws a trend line (with a soft
// area fill and a highlighted last point) for a short series of numbers. Used
// for score trajectories in history/dashboard. Pure, presentational.

export function MiniSparkline({
  values,
  width = 132,
  height = 36,
  tone = "primary",
  min = 0,
  max = 100,
}: {
  values: number[];
  width?: number;
  height?: number;
  tone?: "primary" | "emerald" | "amber" | "rose";
  min?: number;
  max?: number;
}) {
  const stroke = {
    primary: "hsl(var(--primary))",
    emerald: "#16a34a",
    amber: "#f59e0b",
    rose: "#e11d48",
  }[tone];

  if (values.length < 2) {
    return (
      <svg width={width} height={height} role="img" aria-label="Not enough data for a trend">
        <line
          x1={4}
          y1={height / 2}
          x2={width - 4}
          y2={height / 2}
          stroke="currentColor"
          strokeDasharray="3 3"
          className="text-muted-foreground/40"
        />
      </svg>
    );
  }

  const pad = 3;
  const span = Math.max(1, max - min);
  const stepX = (width - pad * 2) / (values.length - 1);
  const points = values.map((v, i) => {
    const clamped = Math.max(min, Math.min(max, v));
    const x = pad + i * stepX;
    const y = pad + (1 - (clamped - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const line = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${points[points.length - 1][0].toFixed(1)},${height - pad} L${points[0][0].toFixed(1)},${height - pad} Z`;
  const [lastX, lastY] = points[points.length - 1];
  const gid = `spark-${tone}-${values.length}`;

  return (
    <svg width={width} height={height} role="img" aria-label="Score trend">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity={0.22} />
          <stop offset="100%" stopColor={stroke} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={stroke} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={lastX} cy={lastY} r={3} fill={stroke} />
    </svg>
  );
}
