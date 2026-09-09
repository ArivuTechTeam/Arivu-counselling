"use client";

/**
 * A short celebratory burst of colourful sparks ("crackers"), rendered inside a
 * relatively-positioned parent. Used when a teacher approves a question so the
 * change is impossible to miss — without a pop-up (there can be 50 cards).
 *
 * Pure CSS/DOM, no dependency. Directions are computed deterministically from
 * the particle index (no Math.random) so there's no SSR/hydration mismatch, and
 * the whole thing is hidden under `prefers-reduced-motion` (see globals.css).
 */

const COLORS = [
  "#16a34a", // brand green
  "#34d399", // mint
  "#fbbf24", // gold
  "#f472b6", // pink
  "#60a5fa", // blue
  "#a78bfa", // violet
];

export function SparkBurst({ count = 16 }: { count?: number }) {
  return (
    <span
      className="pointer-events-none absolute right-6 top-4 z-20"
      aria-hidden="true"
    >
      {Array.from({ length: count }).map((_, i) => {
        // Radiate evenly around the circle, with a little variation by ring.
        const angle = (Math.PI * 2 * i) / count + (i % 2) * 0.35;
        const distance = 24 + (i % 4) * 13; // 24–63px
        const dx = Math.round(Math.cos(angle) * distance);
        const dy = Math.round(Math.sin(angle) * distance);
        const size = 5 + (i % 3) * 2; // 5–9px
        return (
          <span
            key={i}
            className="spark"
            style={{
              width: size,
              height: size,
              background: COLORS[i % COLORS.length],
              animationDelay: `${(i % 3) * 25}ms`,
              // Custom props consumed by the `spark-fly` keyframes.
              ["--dx" as string]: `${dx}px`,
              ["--dy" as string]: `${dy}px`,
            }}
          />
        );
      })}
    </span>
  );
}
