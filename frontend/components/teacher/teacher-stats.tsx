"use client";

import * as React from "react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Skeleton, SkeletonStats } from "@/components/ui/skeleton";
import { ErrorCard } from "@/components/ui/error-card";
import { listDocuments, listQuizSets } from "@/lib/api";

function useCountUp(target: number, on: boolean, ms = 900) {
  const [v, setV] = useState(0);
  const raf = useRef<number>();
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
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [target, on, ms]);
  return v;
}

function Icon({ children }: { children: React.ReactNode }) {
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
const DocIcon = () => (
  <Icon>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <path d="M14 2v6h6" />
  </Icon>
);
const LayersIcon = () => (
  <Icon>
    <path d="m12 2 9 5-9 5-9-5 9-5Z" />
    <path d="m3 12 9 5 9-5" />
    <path d="m3 17 9 5 9-5" />
  </Icon>
);
const CheckIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="10" />
    <path d="m9 12 2 2 4-4" />
  </Icon>
);
const PencilIcon = () => (
  <Icon>
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
  </Icon>
);

function MetricTile({
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

export function TeacherStats() {
  const [docs, setDocs] = useState<number | null>(null);
  const [sets, setSets] = useState<number | null>(null);
  const [published, setPublished] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    Promise.all([listDocuments(), listQuizSets()])
      .then(([documents, s]) => {
        setDocs(documents.length);
        setSets(s.length);
        setPublished(s.filter((x) => x.status === "published").length);
      })
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    load();
  }, []);

  const ready = docs !== null && sets !== null;
  const drafts = Math.max(0, (sets ?? 0) - (published ?? 0));
  const pubPct = sets ? Math.round(((published ?? 0) / sets) * 100) : 0;

  const docsA = useCountUp(docs ?? 0, ready);
  const setsA = useCountUp(sets ?? 0, ready);
  const pubA = useCountUp(published ?? 0, ready);
  const draftsA = useCountUp(drafts, ready);

  if (error) return <ErrorCard message={error} onRetry={load} />;
  if (!ready) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-40 w-full rounded-2xl sm:h-44" />
        <SkeletonStats />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Hero */}
      <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-8 -top-10 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
        <div className="pointer-events-none absolute -bottom-16 right-32 h-52 w-52 rounded-full bg-[#7ae582]/20 blur-3xl" />
        <div className="relative flex flex-wrap items-center justify-between gap-6">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">
              Teaching workspace
            </p>
            <h2 className="mt-2 text-2xl font-bold leading-tight sm:text-[28px]">
              <span className="text-[#9ff0a6]">{setsA}</span> quizzes from{" "}
              <span className="text-[#9ff0a6]">{docsA}</span> documents.
            </h2>
            <p className="mt-2 text-sm text-white/80">
              {pubA} published · {draftsA} in draft.
            </p>
            <Link
              href="/dashboard/teacher/generate"
              className="mt-4 inline-flex items-center gap-1 rounded-md bg-white/15 px-4 py-2 text-sm font-medium text-white backdrop-blur transition-colors hover:bg-white/25"
            >
              Create quiz →
            </Link>
          </div>

          {/* published ring */}
          <div
            className="relative flex h-28 w-28 shrink-0 items-center justify-center rounded-full transition-all duration-700 ease-out"
            style={{
              background: `conic-gradient(#7ae582 ${pubPct * 3.6}deg, rgba(255,255,255,0.16) 0deg)`,
            }}
          >
            <div className="flex h-[94px] w-[94px] flex-col items-center justify-center rounded-full bg-[#15603d]">
              <span className="text-3xl font-bold">{pubA}</span>
              <span className="text-[10px] uppercase tracking-widest text-white/70">
                published
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Tiles */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricTile
          label="Documents"
          value={docsA}
          gradient="from-card to-blue-50/70"
          chip="bg-blue-500/10 text-blue-600"
          icon={<DocIcon />}
          delay={0}
        />
        <MetricTile
          label="Quizzes"
          value={setsA}
          gradient="from-card to-brand-50/70"
          chip="bg-brand-500/10 text-brand-600"
          icon={<LayersIcon />}
          delay={60}
        />
        <MetricTile
          label="Published"
          value={pubA}
          gradient="from-card to-emerald-50/70"
          chip="bg-emerald-500/10 text-emerald-600"
          icon={<CheckIcon />}
          delay={120}
        />
        <MetricTile
          label="In draft"
          value={draftsA}
          gradient="from-card to-amber-50/70"
          chip="bg-amber-500/10 text-amber-600"
          icon={<PencilIcon />}
          delay={180}
        />
      </div>
    </div>
  );
}
