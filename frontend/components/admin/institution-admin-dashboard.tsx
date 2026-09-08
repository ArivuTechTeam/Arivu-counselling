"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { AlertBanner } from "@/app/dashboard/institution-admin/_components/alert-banner";
import { AtRiskStudentsCard } from "@/app/dashboard/institution-admin/_components/at-risk-students-card";
import { CourseHealthCard } from "@/app/dashboard/institution-admin/_components/course-health-card";
import { QuickActionsBar } from "@/app/dashboard/institution-admin/_components/quick-actions-bar";
import { TeacherActivityCard } from "@/app/dashboard/institution-admin/_components/teacher-activity-card";
import { TrendWidget } from "@/app/dashboard/institution-admin/_components/trend-widget";
import { QuizDrilldownModal } from "@/app/dashboard/institution-admin/analytics/_components/quiz-drilldown-modal";
import { StudentPerformanceModal } from "@/app/dashboard/institution-admin/analytics/_components/student-performance-modal";
import { QuizPerformanceModal } from "@/app/dashboard/institution-admin/quizzes/_components/quiz-performance-modal";
import { CheckIcon, GradIcon, LayersIcon, MetricTile, UsersIcon, useCountUp } from "@/components/admin/dashboard-kit";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorCard } from "@/components/ui/error-card";
import {
  AdminQuizSet,
  InstitutionAnalytics,
  InstitutionOverview,
  QualityFinding,
  getAdminQuizSets,
  getInstitutionAnalytics,
  getInstitutionOverview,
} from "@/lib/api";

const BRAND = "#15603d";
type Drilldown = { type: "course" | "teacher"; id: string; name: string };
type AtRiskStudent = InstitutionAnalytics["at_risk_students"][number];

function formatDate(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function accuracyTone(value: number) {
  if (value >= 70) return "text-emerald-700";
  if (value >= 40) return "text-amber-700";
  return "text-rose-700";
}

function DashboardSkeleton() {
  return (
    <div className="flex animate-pulse flex-col gap-6">
      <div className="h-44 rounded-2xl bg-muted" />
      <div className="h-32 rounded-2xl bg-muted" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, index) => <div key={index} className="h-24 rounded-xl bg-muted" />)}
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <div className="h-80 rounded-xl bg-muted" />
        <div className="h-80 rounded-xl bg-muted" />
      </div>
    </div>
  );
}

export function InstitutionAdminDashboard() {
  const router = useRouter();
  const [overview, setOverview] = useState<InstitutionOverview | null>(null);
  const [analytics, setAnalytics] = useState<InstitutionAnalytics | null>(null);
  const [quizzes, setQuizzes] = useState<AdminQuizSet[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [alertsVisible, setAlertsVisible] = useState(true);
  const [drilldown, setDrilldown] = useState<Drilldown | null>(null);
  const [pendingOpen, setPendingOpen] = useState(false);
  const [atRiskOpen, setAtRiskOpen] = useState(false);
  const [selectedStudent, setSelectedStudent] = useState<AtRiskStudent | null>(null);
  const [selectedQuiz, setSelectedQuiz] = useState<AdminQuizSet | null>(null);

  function load() {
    setError(null);
    Promise.all([getInstitutionOverview(), getInstitutionAnalytics(), getAdminQuizSets()])
      .then(([overviewData, analyticsData, quizRows]) => {
        setOverview(overviewData);
        setAnalytics(analyticsData);
        setQuizzes(quizRows);
      })
      .catch((reason) => setError(reason.message));
  }

  useEffect(load, []);

  const ready = overview !== null && analytics !== null;
  const teachers = useCountUp(overview?.teachers ?? 0, ready);
  const students = useCountUp(overview?.students ?? 0, ready);
  const published = useCountUp(overview?.published_quizzes ?? 0, ready);
  const attempts = useCountUp(overview?.attempts ?? 0, ready);
  const drafts = useCountUp(overview?.draft_quizzes ?? 0, ready);
  const activeStudents = useCountUp(analytics?.summary.active_week ?? 0, ready);

  const drilldownQuizzes = useMemo(() => {
    if (!drilldown) return [];
    return quizzes
      .filter((quiz) => drilldown.type === "course" ? quiz.course_id === drilldown.id : quiz.teacher_id === drilldown.id)
      .sort((a, b) => b.attempts_count - a.attempts_count || a.avg_accuracy - b.avg_accuracy);
  }, [drilldown, quizzes]);

  const pendingQuizzes = useMemo(
    () => quizzes
      .filter((quiz) => quiz.review_status.pending + quiz.review_status.needs_edit > 0)
      .sort((a, b) => b.review_status.pending + b.review_status.needs_edit - (a.review_status.pending + a.review_status.needs_edit)),
    [quizzes],
  );

  const recentQuizzes = useMemo(
    () => [...quizzes]
      .sort((a, b) => Date.parse(b.created_at ?? "1970-01-01") - Date.parse(a.created_at ?? "1970-01-01"))
      .slice(0, 5),
    [quizzes],
  );

  function openFinding(finding: QualityFinding) {
    if (finding.action_type === "pending_review") {
      setPendingOpen(true);
      return;
    }
    if (finding.action_type === "at_risk") {
      setSelectedStudent(null);
      setAtRiskOpen(true);
      return;
    }
    if ((finding.action_type === "course" || finding.action_type === "teacher") && finding.action_id) {
      const name = finding.action_type === "course"
        ? analytics?.course_perf.find((course) => course.course_id === finding.action_id)?.name
        : analytics?.teacher_activity.find((teacher) => teacher.teacher_id === finding.action_id)?.name;
      setDrilldown({ type: finding.action_type, id: finding.action_id, name: name ?? "Selected" });
      return;
    }
    router.push("/dashboard/institution-admin/analytics");
  }

  if (error) return <ErrorCard message={error} onRetry={load} />;
  if (!overview || !analytics) return <DashboardSkeleton />;

  const trend = analytics.trend;
  const trendUp = trend.delta >= 0;
  const updated = new Date(analytics.updated_at);
  const totalActivity = analytics.activity.reduce((sum, day) => sum + day.attempts, 0);

  return (
    <div className="flex flex-col gap-6 pb-8">
      <section className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-10 -top-12 h-48 w-48 rounded-full bg-white/10 blur-2xl" />
        <div className="relative grid items-center gap-6 lg:grid-cols-[1fr_auto]">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">Institution operations hub</p>
              <span className="text-xs text-white/60">Updated {updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
            </div>
            <h1 className="mt-3 text-2xl font-bold sm:text-3xl">
              <span className="text-[#9ff0a6]">{teachers}</span> teachers and <span className="text-[#9ff0a6]">{students}</span> students · {analytics.summary.avg_accuracy}% average accuracy
            </h1>
            <p className="mt-2 text-sm text-white/80">{overview.courses} courses · {overview.subjects} subjects · {overview.documents} documents</p>
            <p className={`mt-4 inline-flex rounded-full px-3 py-1.5 text-sm font-semibold ${trendUp ? "bg-emerald-300/15 text-emerald-100" : "bg-rose-300/15 text-rose-100"}`}>
              {trend.delta === 0 ? "→" : trendUp ? "↑" : "↓"} {Math.abs(trend.percentage_change)}% engagement · {trend.attempts_last7} this week vs {trend.attempts_prev7} last week
            </p>
          </div>
          <div className="flex h-28 w-28 items-center justify-center rounded-full" style={{ background: `conic-gradient(#7ae582 ${analytics.summary.avg_accuracy * 3.6}deg, rgba(255,255,255,.16) 0)` }}>
            <div className="flex h-[94px] w-[94px] flex-col items-center justify-center rounded-full bg-[#15603d]">
              <strong className="text-3xl">{analytics.summary.avg_accuracy}%</strong>
              <span className="text-[9px] uppercase tracking-widest text-white/70">accuracy</span>
            </div>
          </div>
        </div>
      </section>

      {alertsVisible && <div id="dashboard-findings"><AlertBanner findings={analytics.findings} onAction={openFinding} onDismiss={() => setAlertsVisible(false)} /></div>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MetricTile label="Students" value={students} gradient="from-card to-emerald-50/70" chip="bg-emerald-500/10 text-emerald-600" icon={<GradIcon />} />
        <MetricTile label="Teachers" value={teachers} gradient="from-card to-blue-50/70" chip="bg-blue-500/10 text-blue-600" icon={<UsersIcon />} delay={40} />
        <MetricTile label="Published" value={published} gradient="from-card to-brand-50/70" chip="bg-brand-500/10 text-brand-600" icon={<CheckIcon />} delay={80} />
        <MetricTile label="Graded attempts" value={attempts} gradient="from-card to-amber-50/70" chip="bg-amber-500/10 text-amber-600" icon={<LayersIcon />} delay={120} />
        <MetricTile label="Draft quizzes" value={drafts} gradient="from-card to-orange-50/70" chip="bg-orange-500/10 text-orange-600" icon={<LayersIcon />} delay={160} />
        <MetricTile label="Active this week" value={activeStudents} gradient="from-card to-teal-50/70" chip="bg-teal-500/10 text-teal-600" icon={<UsersIcon />} delay={200} />
      </div>

      <QuickActionsBar
        pendingReviewCount={analytics.pipeline.pending_review}
        onPending={() => setPendingOpen(true)}
        onFindings={() => {
          setAlertsVisible(true);
          window.setTimeout(() => document.getElementById("dashboard-findings")?.scrollIntoView({ behavior: "smooth" }), 0);
        }}
      />

      <Card>
        <CardHeader>
          <CardTitle>Quiz activity · last 14 days</CardTitle>
          <CardDescription>{totalActivity} graded attempts in this period, with week-over-week context.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={analytics.activity} margin={{ top: 8, right: 12, bottom: 0, left: -20 }}>
                <defs><linearGradient id="dashboardActivity" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={BRAND} stopOpacity={0.3} /><stop offset="100%" stopColor={BRAND} stopOpacity={0} /></linearGradient></defs>
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#7c817d" }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#7c817d" }} />
                <Tooltip />
                <Area type="monotone" dataKey="attempts" stroke={BRAND} strokeWidth={2.5} fill="url(#dashboardActivity)" dot={{ r: 2.5, fill: BRAND }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <TrendWidget trend={trend} activeStudents={analytics.summary.active_week} />
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <TeacherActivityCard teachers={analytics.teacher_activity} onSelect={(teacher) => setDrilldown({ type: "teacher", id: teacher.teacher_id, name: teacher.name })} />
        <AtRiskStudentsCard
          students={analytics.at_risk_students}
          onSelect={(student) => { setSelectedStudent(student); setAtRiskOpen(true); }}
          onViewAll={() => { setSelectedStudent(null); setAtRiskOpen(true); }}
        />
      </div>

      <CourseHealthCard courses={analytics.course_perf} onSelect={(course) => setDrilldown({ type: "course", id: course.course_id, name: course.name })} />

      <Card>
        <CardHeader className="gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div><CardTitle>Recent quiz sets</CardTitle><CardDescription>Latest content with engagement and review health.</CardDescription></div>
          <button type="button" onClick={() => router.push("/dashboard/institution-admin/quizzes")} className="text-sm font-semibold text-primary hover:underline">View all quizzes →</button>
        </CardHeader>
        <CardContent>
          {recentQuizzes.length === 0 ? <p className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">New teacher quiz sets will appear here.</p> : (
            <div className="overflow-x-auto rounded-xl border">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="bg-secondary/40 text-left text-[11px] uppercase tracking-wider text-muted-foreground"><tr><th className="px-4 py-3 font-semibold">Quiz</th><th className="px-4 py-3 font-semibold">Status</th><th className="px-4 py-3 text-right font-semibold">Attempts</th><th className="px-4 py-3 text-right font-semibold">Accuracy</th><th className="px-4 py-3 text-right font-semibold">Review</th><th className="px-4 py-3 text-right font-semibold">Created</th><th className="px-4 py-3 text-right font-semibold">Action</th></tr></thead>
                <tbody>
                  {recentQuizzes.map((quiz) => {
                    const pending = quiz.review_status.pending + quiz.review_status.needs_edit;
                    return <tr key={quiz.id} className="border-t hover:bg-accent/60">
                      <td className="px-4 py-3"><strong className="block">{quiz.title}</strong><span className="text-xs text-muted-foreground">{[quiz.course, quiz.subject, quiz.teacher ?? "Former faculty"].filter(Boolean).join(" · ")}</span></td>
                      <td className="px-4 py-3"><span className={`rounded-full px-2 py-1 text-xs font-semibold capitalize ${quiz.status === "published" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>{quiz.status}</span></td>
                      <td className="px-4 py-3 text-right font-semibold">{quiz.attempts_count}</td>
                      <td className={`px-4 py-3 text-right font-semibold ${quiz.attempts_count ? accuracyTone(quiz.avg_accuracy) : "text-muted-foreground"}`}>{quiz.attempts_count ? `${quiz.avg_accuracy}%` : "—"}</td>
                      <td className="px-4 py-3 text-right">{pending ? <span className="rounded-full bg-violet-100 px-2 py-1 text-xs font-semibold text-violet-700">{pending} pending</span> : <span className="text-xs text-muted-foreground">Clear</span>}</td>
                      <td className="px-4 py-3 text-right text-muted-foreground">{formatDate(quiz.created_at)}</td>
                      <td className="px-4 py-3 text-right"><button type="button" onClick={() => setSelectedQuiz(quiz)} className="font-semibold text-primary hover:underline">View →</button></td>
                    </tr>;
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {drilldown && <QuizDrilldownModal title={`${drilldown.name} quizzes`} description={`${drilldown.type === "course" ? "Course" : "Teacher"} quizzes, ordered by engagement and then lowest accuracy.`} quizzes={drilldownQuizzes} onClose={() => setDrilldown(null)} onSelect={(quiz) => { setDrilldown(null); setSelectedQuiz(quiz); }} />}
      {pendingOpen && <QuizDrilldownModal title="Quizzes awaiting review" description="Quizzes with pending or needs-edit questions, highest backlog first." quizzes={pendingQuizzes} onClose={() => setPendingOpen(false)} onSelect={(quiz) => { setPendingOpen(false); setSelectedQuiz(quiz); }} />}
      {atRiskOpen && <StudentPerformanceModal students={analytics.at_risk_students} initialStudent={selectedStudent} onClose={() => { setAtRiskOpen(false); setSelectedStudent(null); }} />}
      {selectedQuiz && <QuizPerformanceModal quiz={selectedQuiz} onClose={() => setSelectedQuiz(null)} />}
    </div>
  );
}
