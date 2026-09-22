"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

const AreaTrendChart = dynamic(
  () =>
    import("@/components/shared/area-trend-chart").then(
      (module) => module.AreaTrendChart,
    ),
  {
    ssr: false,
    loading: () => <div className="h-full w-full animate-pulse rounded-xl bg-muted" />,
  },
);

export type TrendDatum = object;

type DeferredAreaTrendChartProps = {
  data: TrendDatum[];
  xKey: string;
  yKey: string;
  color: string;
  gradientId: string;
  yDomain?: [number, number];
  showGrid?: boolean;
};

/**
 * Keeps Recharts out of the critical dashboard bundle and does not request its
 * chunk until the chart is close to the viewport.
 */
export function DeferredAreaTrendChart(props: DeferredAreaTrendChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = containerRef.current;
    if (!node || visible) return;

    if (!("IntersectionObserver" in window)) {
      setVisible(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "240px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible]);

  return (
    <div ref={containerRef} className="h-full w-full">
      {visible ? (
        <AreaTrendChart {...props} />
      ) : (
        <div className="h-full w-full animate-pulse rounded-xl bg-muted" />
      )}
    </div>
  );
}
