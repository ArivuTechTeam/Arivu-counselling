"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  BuildingIcon,
  GradIcon,
  HeroBanner,
  LayersIcon,
  MetricTile,
  UsersIcon,
  useCountUp,
} from "@/components/admin/dashboard-kit";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton, SkeletonStats } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { PlatformOverview, getPlatformOverview } from "@/lib/api";

const BRAND = "#15603d";

function acc(pct: number) {
  return pct >= 70 ? "#00a651" : pct >= 40 ? "#f5a623" : "#ff6b7a";
}

function PipeRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className={`flex items-center justify-between rounded-lg px-3 py-2 ${tone}`}>
      <span className="font-medium">{label}</span>
      <span className="font-bold">{value}</span>
    </div>
  );
}

export default function PlatformOverviewPage() {
  const [s, setS] = useState<PlatformOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    getPlatformOverview()
      .then(setS)
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  const ready = s !== null;
  const inst = useCountUp(s?.institutions ?? 0, ready);
  const teachers = useCountUp(s?.teachers ?? 0, ready);
  const students = useCountUp(s?.students ?? 0, ready);
  const quizSets = useCountUp(s?.quiz_sets ?? 0, ready);
  const approval = useCountUp(s?.approval_rate ?? 0, ready);

  if (error) return <ErrorCard message={error} onRetry={load} />;

  if (!ready) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-40 w-full rounded-2xl" />
        <SkeletonStats />
      </div>
    );
  }

  const rows = s?.institutions_table ?? [];
  const pipe = s?.pipeline ?? {
    pending_review: 0,
    approved: 0,
    rejected: 0,
    needs_edit: 0,
  };

  return (
    <div className="flex flex-col gap-6">
      <HeroBanner
        eyebrow="Platform command center"
        title={
          <>
            <span className="text-[#9ff0a6]">{inst}</span>{" "}
            {(s?.institutions ?? 0) === 1 ? "institution" : "institutions"} on the
            platform.
          </>
        }
        subtitle={`${s?.teachers ?? 0} teachers · ${s?.students ?? 0} students · ${
          s?.admins ?? 0
        } admins · ${s?.quiz_sets ?? 0} quiz sets`}
        ring={{ value: `${approval}%`, label: "approved", pct: ready ? s!.approval_rate : 0 }}
      />

      {/* KPI tiles */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricTile
          label="Institutions"
          value={ready ? inst : "—"}
          gradient="from-card to-brand-50/70"
          chip="bg-brand-500/10 text-brand-600"
          icon={<BuildingIcon />}
          delay={0}
        />
        <MetricTile
          label="Teachers"
          value={ready ? teachers : "—"}
          gradient="from-card to-blue-50/70"
          chip="bg-blue-500/10 text-blue-600"
          icon={<UsersIcon />}
          delay={60}
        />
        <MetricTile
          label="Students"
          value={ready ? students : "—"}
          gradient="from-card to-emerald-50/70"
          chip="bg-emerald-500/10 text-emerald-600"
          icon={<GradIcon />}
          delay={120}
        />
        <MetricTile
          label="Quiz sets"
          value={ready ? quizSets : "—"}
          gradient="from-card to-amber-50/70"
          chip="bg-amber-500/10 text-amber-600"
          icon={<LayersIcon />}
          delay={180}
        />
      </div>

      {/* Platform activity + question quality */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="animate-rise lg:col-span-2">
          <CardHeader>
            <CardTitle>Platform activity</CardTitle>
            <CardDescription>
              Graded quiz attempts across all institutions, last 14 days.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={s?.activity ?? []}
                  margin={{ top: 8, right: 12, bottom: 0, left: -20 }}
                >
                  <defs>
                    <linearGradient id="pactFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={BRAND} stopOpacity={0.28} />
                      <stop offset="100%" stopColor={BRAND} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#8b8b85" }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#8b8b85" }} />
                  <Tooltip />
                  <Area
                    type="monotone"
                    dataKey="attempts"
                    stroke={BRAND}
                    strokeWidth={2.5}
                    fill="url(#pactFill)"
                    dot={{ r: 2.5, fill: BRAND }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card className="animate-rise lg:col-span-1" style={{ animationDelay: "60ms" }}>
          <CardHeader>
            <CardTitle>Question quality</CardTitle>
            <CardDescription>Review pipeline across the platform.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div>
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-muted-foreground">Approval rate</span>
                <span
                  className="text-2xl font-bold"
                  style={{ color: acc(s?.approval_rate ?? 0) }}
                >
                  {s?.approval_rate ?? 0}%
                </span>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Share of reviewed questions currently approved.
              </p>
            </div>
            <div className="flex flex-col gap-2 text-sm">
              <PipeRow label="Approved" value={pipe.approved} tone="bg-emerald-50 text-emerald-700" />
              <PipeRow label="Pending review" value={pipe.pending_review} tone="bg-amber-50 text-amber-700" />
              <PipeRow label="Needs edit" value={pipe.needs_edit} tone="bg-orange-50 text-orange-700" />
              <PipeRow label="Rejected" value={pipe.rejected} tone="bg-rose-50 text-rose-700" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Institutions table */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Institutions</CardTitle>
          <CardDescription>Every institution on the platform at a glance.</CardDescription>
        </CardHeader>
        <CardContent>
          {rows.length === 0 ? (
            <EmptyState
              title="No institutions yet"
              message="Onboard your first institution to get started."
              action={
                <Link
                  href="/dashboard/super-admin/institutions"
                  className="inline-flex items-center gap-1 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
                >
                  Onboard an institution
                </Link>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-2 py-2 font-medium">Institution</th>
                    <th className="px-2 py-2 text-right font-medium">Teachers</th>
                    <th className="px-2 py-2 text-right font-medium">Students</th>
                    <th className="px-2 py-2 text-right font-medium">Quiz sets</th>
                    <th className="px-2 py-2 text-right font-medium">Attempts</th>
                    <th className="px-2 py-2 text-right font-medium">Accuracy</th>
                    <th className="px-2 py-2 text-right font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="border-b last:border-0 hover:bg-accent">
                      <td className="px-2 py-2.5">
                        <div className="font-medium text-foreground">{r.name}</div>
                        <div className="text-xs text-muted-foreground">
                          {r.subdomain ? `${r.subdomain} · ` : ""}
                          {r.plan_tier ?? "free"}
                        </div>
                      </td>
                      <td className="px-2 py-2.5 text-right text-muted-foreground">{r.teachers}</td>
                      <td className="px-2 py-2.5 text-right text-muted-foreground">{r.students}</td>
                      <td className="px-2 py-2.5 text-right text-muted-foreground">
                        {r.quiz_sets}
                        <span className="text-xs text-muted-foreground/70"> ({r.published} pub)</span>
                      </td>
                      <td className="px-2 py-2.5 text-right text-muted-foreground">{r.attempts}</td>
                      <td
                        className="px-2 py-2.5 text-right font-semibold"
                        style={{ color: acc(r.accuracy) }}
                      >
                        {r.attempts > 0 ? `${r.accuracy}%` : "—"}
                      </td>
                      <td className="px-2 py-2.5 text-right">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            r.is_active
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-muted text-muted-foreground"
                          }`}
                        >
                          {r.is_active ? "active" : "inactive"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="mt-4">
            <Link
              href="/dashboard/super-admin/institutions"
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              Manage institutions →
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
