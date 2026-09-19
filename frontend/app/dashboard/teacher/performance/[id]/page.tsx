"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonCards } from "@/components/ui/skeleton";
import { TeacherQuizPerformance, getTeacherQuizPerformance } from "@/lib/api";

const pct = (value: number | null) => value === null ? "—" : `${value}%`;

export default function TeacherQuizPerformancePage({ params }: { params: { id: string } }) {
  const [report, setReport] = useState<TeacherQuizPerformance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => {
    setError(null);
    getTeacherQuizPerformance(params.id).then(setReport).catch((reason) => setError(reason.message));
  };
  useEffect(load, [params.id]);
  if (error) return <ErrorCard message={error} onRetry={load} />;
  if (!report) return <SkeletonCards count={4} />;
  const { summary } = report;
  const stats = [
    ["Eligible students", summary.eligible_students], ["Completed", summary.completed_students],
    ["Not started", summary.not_started_students], ["Average score", `${summary.average_accuracy}%`],
  ];
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href="/dashboard/teacher/published-quizzes" className="text-sm text-muted-foreground hover:text-primary">← Published quizzes</Link>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">{report.quiz.title} performance</h1>
          <p className="mt-1 text-sm text-muted-foreground">Results from students enrolled in this quiz&apos;s course.</p>
        </div>
        <Button variant="outline" onClick={load}>Refresh report</Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map(([label, value]) => <div key={String(label)} className="rounded-xl border bg-card p-4 shadow-sm"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p><p className="mt-2 text-2xl font-semibold">{value}</p></div>)}
      </div>
      <section className="rounded-2xl border bg-card p-5 shadow-sm">
        <h2 className="font-semibold">Score distribution</h2>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">{report.score_distribution.map((band) => <div key={band.label} className="rounded-lg bg-muted/50 p-3"><p className="text-sm text-muted-foreground">{band.label}%</p><p className="mt-1 text-xl font-semibold">{band.count}</p></div>)}</div>
        <p className="mt-4 text-sm text-muted-foreground">Highest {summary.highest_accuracy}% · Lowest {summary.lowest_accuracy}% · {summary.total_attempts} graded attempt{summary.total_attempts === 1 ? "" : "s"}</p>
      </section>
      <section className="overflow-hidden rounded-2xl border bg-card shadow-sm">
        <div className="border-b p-5"><h2 className="font-semibold">Student results</h2><p className="mt-1 text-sm text-muted-foreground">Latest and best result for each eligible student.</p></div>
        {report.students.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No students are enrolled in this course yet.</p> : <div className="divide-y">{report.students.map((student) => <div key={student.student_id} className="grid gap-2 px-5 py-4 text-sm sm:grid-cols-[minmax(0,1fr)_90px_90px_100px]"><div><p className="font-medium">{student.student_name}</p><p className="text-muted-foreground">{student.attempts ? `${student.attempts} attempt${student.attempts === 1 ? "" : "s"}` : "Not started"}</p></div><div><p className="text-xs text-muted-foreground">Latest</p><p className="font-medium">{pct(student.latest_accuracy)}</p></div><div><p className="text-xs text-muted-foreground">Best</p><p className="font-medium">{pct(student.best_accuracy)}</p></div><div><span className={student.status === "completed" ? "rounded-full bg-emerald-50 px-2 py-1 text-xs text-emerald-700" : "rounded-full bg-muted px-2 py-1 text-xs text-muted-foreground"}>{student.status === "completed" ? "Completed" : "Not started"}</span></div></div>)}</div>}
      </section>
      <section className="overflow-hidden rounded-2xl border bg-card shadow-sm">
        <div className="border-b p-5"><h2 className="font-semibold">Question accuracy</h2><p className="mt-1 text-sm text-muted-foreground">Lowest-performing questions appear first.</p></div>
        {report.question_performance.length === 0 ? <p className="p-5 text-sm text-muted-foreground">Question accuracy will appear after students submit graded attempts.</p> : <div className="divide-y">{report.question_performance.map((question, index) => <div key={question.question_id} className="flex gap-4 px-5 py-4 text-sm"><span className="text-muted-foreground">{index + 1}</span><p className="min-w-0 flex-1">{question.question_text}</p><p className="shrink-0 font-medium">{question.accuracy}% <span className="font-normal text-muted-foreground">({question.answered})</span></p></div>)}</div>}
      </section>
    </div>
  );
}
