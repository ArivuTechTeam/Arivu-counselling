"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StudentReportButton } from "@/components/shared/pdf-buttons";
import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList, SkeletonStats } from "@/components/ui/skeleton";
import { ClassMonitor, ClassMonitorStudent, getClassMonitor } from "@/lib/api";

const STATUS: Record<string, { label: string; tone: string; color: string }> = {
  strong: { label: "Strong", tone: "bg-emerald-100 text-emerald-700", color: "#00a651" },
  ok: { label: "On track", tone: "bg-amber-100 text-amber-700", color: "#f5a623" },
  at_risk: { label: "At risk", tone: "bg-rose-100 text-rose-700", color: "#ff6b7a" },
  not_started: { label: "Not started", tone: "bg-muted text-muted-foreground", color: "#cbd5e1" },
};

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function Stat({ value, label, color }: { value: number | string; label: string; color?: string }) {
  return (
    <Card className="animate-rise">
      <CardContent className="p-5">
        <div className="text-[28px] font-bold leading-none" style={{ color }}>
          {value}
        </div>
        <div className="mt-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
          {label}
        </div>
      </CardContent>
    </Card>
  );
}

export default function ClassMonitorPage() {
  const [data, setData] = useState<ClassMonitor | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"all" | "at_risk" | "not_started">("all");

  function load() {
    setError(null);
    getClassMonitor()
      .then(setData)
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    load();
  }, []);

  const rows: ClassMonitorStudent[] = useMemo(() => {
    const all = data?.students ?? [];
    if (tab === "at_risk") return all.filter((s) => s.status === "at_risk");
    if (tab === "not_started") return all.filter((s) => s.status === "not_started");
    return all;
  }, [data, tab]);

  const loading = data === null && !error;
  const sm = data?.summary;

  const tabs: { key: typeof tab; label: string; count: number }[] = [
    { key: "all", label: "All students", count: sm?.students ?? 0 },
    { key: "at_risk", label: "At risk", count: sm?.at_risk ?? 0 },
    { key: "not_started", label: "Not started", count: sm?.not_started ?? 0 },
  ];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Class monitor"
        description="Your class roster and how each student is engaging with your quizzes."
      />

      {error ? (
        <ErrorCard message={error} onRetry={load} />
      ) : loading ? (
        <>
          <SkeletonStats />
          <SkeletonList rows={6} />
        </>
      ) : (
        <>
      {/* Summary tiles */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat value={sm?.students ?? 0} label="Students" />
        <Stat value={sm?.active_week ?? 0} label="Active this week" />
        <Stat
          value={`${sm?.class_accuracy ?? 0}%`}
          label="Class accuracy"
          color={STATUS[(sm?.class_accuracy ?? 0) >= 60 ? "strong" : "at_risk"].color}
        />
        <Stat value={sm?.at_risk ?? 0} label="At risk" color={(sm?.at_risk ?? 0) > 0 ? "#ff6b7a" : undefined} />
      </div>

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Roster</CardTitle>
          <CardDescription>
            Each student&apos;s activity to date — quizzes taken, accuracy, best
            score, and when they were last active.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Tabs */}
          <div className="mb-4 flex flex-wrap gap-2">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                  tab === t.key
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-input text-muted-foreground hover:border-primary/40"
                }`}
              >
                {t.label} ({t.count})
              </button>
            ))}
          </div>

          {rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {(data?.students.length ?? 0) === 0
                ? "No students in your courses yet — once students are enrolled and take your quizzes, they'll appear here."
                : "No students in this view."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-2 py-2 font-medium">Student</th>
                    <th className="px-2 py-2 text-right font-medium">Quizzes</th>
                    <th className="px-2 py-2 text-right font-medium">Accuracy</th>
                    <th className="px-2 py-2 text-right font-medium">Best</th>
                    <th className="px-2 py-2 text-right font-medium">Last active</th>
                    <th className="px-2 py-2 text-right font-medium">Status</th>
                    <th className="px-2 py-2 text-right font-medium">Report</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s, i) => {
                    const st = STATUS[s.status] ?? STATUS.ok;
                    return (
                      <tr key={i} className="border-b last:border-0 hover:bg-accent">
                        <td className="px-2 py-2.5">
                          <div className="flex items-center gap-3">
                            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
                              {s.initials}
                            </span>
                            <span className="font-medium text-foreground">{s.name}</span>
                          </div>
                        </td>
                        <td className="px-2 py-2.5 text-right text-muted-foreground">
                          {s.attempts}
                        </td>
                        <td
                          className="px-2 py-2.5 text-right font-semibold"
                          style={{ color: s.attempts > 0 ? st.color : "#cbd5e1" }}
                        >
                          {s.attempts > 0 ? `${s.accuracy}%` : "—"}
                        </td>
                        <td className="px-2 py-2.5 text-right text-muted-foreground">
                          {s.attempts > 0 ? `${s.best}%` : "—"}
                        </td>
                        <td className="px-2 py-2.5 text-right text-muted-foreground">
                          {fmtDate(s.last_active)}
                        </td>
                        <td className="px-2 py-2.5 text-right">
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-medium ${st.tone}`}
                          >
                            {st.label}
                          </span>
                        </td>
                        <td className="px-2 py-2.5 text-right">
                          {s.attempts > 0 ? (
                            <StudentReportButton studentId={s.id} studentName={s.name} />
                          ) : (
                            <span className="text-xs text-muted-foreground/60">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
        </>
      )}
    </div>
  );
}
