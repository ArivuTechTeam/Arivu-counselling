"use client";

import * as React from "react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

/** Count a number up from 0 (ease-out) once `on` becomes true. */
export function useCountUp(target: number, on: boolean, ms = 900) {
  const [v, setV] = useState(0);
  const raf = useRef<number | null>(null);
  useEffect(() => {
    if (!on) return;
    const start = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / ms);
      setV(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current);
    };
  }, [target, on, ms]);
  return v;
}

// --- inline icons (lucide paths, 2px stroke) ------------------------------
function Svg({ children }: { children: React.ReactNode }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}
export const UsersIcon = () => (
  <Svg>
    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </Svg>
);
export const GradIcon = () => (
  <Svg>
    <path d="M22 10 12 5 2 10l10 5 10-5Z" />
    <path d="M6 12v5c3 3 9 3 12 0v-5" />
  </Svg>
);
export const BookIcon = () => (
  <Svg>
    <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
    <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
  </Svg>
);
export const LayersIcon = () => (
  <Svg>
    <path d="m12 2 9 5-9 5-9-5 9-5Z" />
    <path d="m3 12 9 5 9-5" />
    <path d="m3 17 9 5 9-5" />
  </Svg>
);
export const BuildingIcon = () => (
  <Svg>
    <rect width="16" height="20" x="4" y="2" rx="2" />
    <path d="M9 22v-4h6v4" />
    <path d="M8 6h.01M16 6h.01M12 6h.01M12 10h.01M16 10h.01M8 10h.01M12 14h.01M16 14h.01M8 14h.01" />
  </Svg>
);
export const CheckIcon = () => (
  <Svg>
    <circle cx="12" cy="12" r="10" />
    <path d="m9 12 2 2 4-4" />
  </Svg>
);

export function MetricTile({
  label,
  value,
  gradient,
  chip,
  icon,
  delay = 0,
}: {
  label: string;
  value: string | number;
  gradient: string;
  chip: string;
  icon: React.ReactNode;
  delay?: number;
}) {
  return (
    <div
      style={{ animationDelay: `${delay}ms` }}
      className={`animate-rise relative overflow-hidden rounded-2xl border bg-gradient-to-br ${gradient} p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[28px] font-bold leading-none tracking-tight text-foreground">
            {value}
          </div>
          <div className="mt-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            {label}
          </div>
        </div>
        <span
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${chip}`}
        >
          {icon}
        </span>
      </div>
    </div>
  );
}

export function HeroBanner({
  eyebrow,
  title,
  subtitle,
  cta,
  ring,
}: {
  eyebrow: string;
  title: React.ReactNode;
  subtitle?: string;
  cta?: { href: string; label: string };
  ring?: { value: number | string; label: string; pct: number };
}) {
  return (
    <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
      <div className="pointer-events-none absolute -right-8 -top-10 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
      <div className="pointer-events-none absolute -bottom-16 right-32 h-52 w-52 rounded-full bg-[#7ae582]/20 blur-3xl" />
      <div className="relative flex flex-wrap items-center justify-between gap-6">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">
            {eyebrow}
          </p>
          <h2 className="mt-2 text-2xl font-bold leading-tight sm:text-[28px]">
            {title}
          </h2>
          {subtitle && <p className="mt-2 text-sm text-white/80">{subtitle}</p>}
          {cta && (
            <Link
              href={cta.href}
              className="mt-4 inline-flex items-center gap-1 rounded-md bg-white/15 px-4 py-2 text-sm font-medium text-white backdrop-blur transition-colors hover:bg-white/25"
            >
              {cta.label}
            </Link>
          )}
        </div>
        {ring && (
          <div
            className="relative flex h-28 w-28 shrink-0 items-center justify-center rounded-full transition-all duration-700 ease-out"
            style={{
              background: `conic-gradient(#7ae582 ${ring.pct * 3.6}deg, rgba(255,255,255,0.16) 0deg)`,
            }}
          >
            <div className="flex h-[94px] w-[94px] flex-col items-center justify-center rounded-full bg-[#15603d]">
              <span className="text-3xl font-bold">{ring.value}</span>
              <span className="text-[10px] uppercase tracking-widest text-white/70">
                {ring.label}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
