"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export function AreaTrendChart({
  data,
  xKey,
  yKey,
  color,
  gradientId,
  yDomain,
  showGrid = false,
}: {
  data: object[];
  xKey: string;
  yKey: string;
  color: string;
  gradientId: string;
  yDomain?: [number, number];
  showGrid?: boolean;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart
        data={data}
        margin={{ top: 8, right: 12, bottom: 0, left: -20 }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#eee" />}
        <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: "#8b8b85" }} />
        <YAxis
          allowDecimals={false}
          domain={yDomain}
          tick={{ fontSize: 11, fill: "#8b8b85" }}
        />
        <Tooltip />
        <Area
          type="monotone"
          dataKey={yKey}
          stroke={color}
          strokeWidth={2.5}
          fill={`url(#${gradientId})`}
          dot={{ r: 2.5, fill: color }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
