"use client";

import { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { AdminQuizSet, InstitutionAnalytics, QualityFinding, getAdminQuizSets, getInstitutionAnalytics } from "@/lib/api";
import { QuizPerformanceModal } from "../quizzes/_components/quiz-performance-modal";
import { QuizDrilldownModal } from "./_components/quiz-drilldown-modal";
import { StudentPerformanceModal } from "./_components/student-performance-modal";

const BRAND = "#15603d";
const SEVERITY = {
  critical: { label: "Critical", color: "#ff6b7a", chip: "bg-rose-100 text-rose-700" },
  warn: { label: "Improve", color: "#f5a623", chip: "bg-amber-100 text-amber-700" },
  good: { label: "Good", color: "#00a651", chip: "bg-emerald-100 text-emerald-700" },
  info: { label: "Note", color: "#6366f1", chip: "bg-indigo-100 text-indigo-700" },
} satisfies Record<QualityFinding["severity"], { label: string; color: string; chip: string }>;

type Teacher = InstitutionAnalytics["teacher_activity"][number];
type Course = InstitutionAnalytics["course_perf"][number];
type Student = InstitutionAnalytics["at_risk_students"][number];
type TeacherSort = "attempts" | "accuracy" | "last_active";
type CourseSort = keyof Pick<Course, "name" | "students" | "published" | "pending_review" | "attempts" | "accuracy">;

function accuracyColor(value: number) { return value >= 70 ? "#00a651" : value >= 40 ? "#f5a623" : "#ff6b7a"; }
function relativeDate(value: string | null) {
  if (!value) return "Never";
  const days = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000));
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return days < 7 ? `${days} days ago` : days < 14 ? "1 week ago" : `${Math.floor(days / 7)} weeks ago`;
}
function StatTile({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return <Card><CardContent className="p-5"><div className="text-[26px] font-bold leading-none" style={{ color }}>{value}</div><div className="mt-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</div></CardContent></Card>;
}
function Skeleton() {
  return <div className="flex animate-pulse flex-col gap-6"><div className="h-28 rounded-2xl bg-muted"/><div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-24 rounded-xl bg-muted"/>)}</div><div className="h-72 rounded-xl bg-muted"/></div>;
}

export default function InstitutionAnalyticsPage() {
  const [data, setData] = useState<InstitutionAnalytics | null>(null);
  const [quizzes, setQuizzes] = useState<AdminQuizSet[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [teacherSort, setTeacherSort] = useState<TeacherSort>("attempts");
  const [showInactive, setShowInactive] = useState(false);
  const [courseSort, setCourseSort] = useState<{ key: CourseSort; direction: "asc" | "desc" }>({ key: "attempts", direction: "desc" });
  const [drilldown, setDrilldown] = useState<{ type: "course" | "teacher"; id: string; name: string } | null>(null);
  const [pendingOpen, setPendingOpen] = useState(false);
  const [atRiskOpen, setAtRiskOpen] = useState(false);
  const [selectedStudent, setSelectedStudent] = useState<Student | null>(null);
  const [selectedQuiz, setSelectedQuiz] = useState<AdminQuizSet | null>(null);

  function load() {
    setLoading(true); setError(null);
    Promise.all([getInstitutionAnalytics(), getAdminQuizSets()])
      .then(([analytics, rows]) => { setData(analytics); setQuizzes(rows); })
      .catch((reason) => setError(reason.message)).finally(() => setLoading(false));
  }
  useEffect(load, []);

  const activeTeachers = useMemo(() => {
    const rows = [...(data?.teacher_activity ?? [])].filter((teacher) => teacher.is_active);
    rows.sort((a, b) => teacherSort === "attempts" ? b.attempts - a.attempts : teacherSort === "accuracy" ? b.accuracy - a.accuracy : Date.parse(b.last_quiz_created ?? "1970-01-01") - Date.parse(a.last_quiz_created ?? "1970-01-01"));
    return rows;
  }, [data, teacherSort]);
  const inactiveTeachers = (data?.teacher_activity ?? []).filter((teacher) => !teacher.is_active);
  const maxAttempts = Math.max(1, ...activeTeachers.map((teacher) => teacher.attempts));
  const sortedCourses = useMemo(() => [...(data?.course_perf ?? [])].sort((a, b) => {
    const left = a[courseSort.key]; const right = b[courseSort.key];
    const result = typeof left === "string" ? left.localeCompare(String(right)) : Number(left) - Number(right);
    return courseSort.direction === "asc" ? result : -result;
  }), [data, courseSort]);
  const drilldownQuizzes = useMemo(() => !drilldown ? [] : quizzes.filter((quiz) => drilldown.type === "course" ? quiz.course_id === drilldown.id : quiz.teacher_id === drilldown.id).sort((a, b) => b.attempts_count - a.attempts_count || a.avg_accuracy - b.avg_accuracy), [drilldown, quizzes]);
  const pendingQuizzes = useMemo(() => quizzes.filter((quiz) => quiz.review_status.pending + quiz.review_status.needs_edit > 0).sort((a, b) => b.review_status.pending - a.review_status.pending), [quizzes]);

  function toggleCourseSort(key: CourseSort) { setCourseSort((current) => ({ key, direction: current.key === key && current.direction === "desc" ? "asc" : "desc" })); }
  function findingAction(finding: QualityFinding) {
    if (finding.action_type === "pending_review") setPendingOpen(true);
    if (finding.action_type === "at_risk") { setSelectedStudent(null); setAtRiskOpen(true); }
    if ((finding.action_type === "course" || finding.action_type === "teacher") && finding.action_id) {
      const name = finding.action_type === "course" ? data?.course_perf.find((row) => row.course_id === finding.action_id)?.name : data?.teacher_activity.find((row) => row.teacher_id === finding.action_id)?.name;
      setDrilldown({ type: finding.action_type, id: finding.action_id, name: name ?? "Selected" });
    }
  }

  if (error) return <div className="flex flex-col gap-6"><PageHeader title="Institution analytics" description="See performance trends and where your institution needs attention."/><ErrorCard message={error} onRetry={load}/></div>;
  if (!data) return <div className="flex flex-col gap-6"><PageHeader title="Institution analytics" description="See performance trends and where your institution needs attention."/><Skeleton/></div>;

  const { summary, trend } = data;
  const trendPct = trend.attempts_prev7 ? Math.round((trend.delta / trend.attempts_prev7) * 1000) / 10 : trend.attempts_last7 ? 100 : 0;
  const trendUp = trend.delta >= 0;
  const maxWeek = Math.max(1, trend.attempts_last7, trend.attempts_prev7);
  const updated = new Date(data.updated_at);

  return <div className="flex flex-col gap-6 pb-8">
    <PageHeader title="Institution analytics" description="See performance trends, find problems, and open the quizzes behind every metric." actions={<div className="flex items-center gap-3"><span className="hidden text-xs text-muted-foreground sm:inline">Updated {updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span><button onClick={load} disabled={loading} className="rounded-lg border bg-card px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:opacity-60">{loading ? "Refreshing…" : "Refresh"}</button></div>}/>

    <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8"><div className="relative flex flex-wrap items-center justify-between gap-6"><div><p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">Institution health</p><h2 className="mt-2 text-2xl font-bold"><span className="text-[#9ff0a6]">{summary.avg_accuracy}%</span> average accuracy across {summary.students} students.</h2><p className="mt-2 text-sm text-white/80">{summary.active_week} active this week · {summary.at_risk} at risk · {summary.published_quizzes} published quizzes</p></div><div className="flex h-24 w-24 items-center justify-center rounded-full" style={{ background: `conic-gradient(#7ae582 ${summary.avg_accuracy * 3.6}deg, rgba(255,255,255,.16) 0)` }}><div className="flex h-20 w-20 flex-col items-center justify-center rounded-full bg-[#15603d]"><strong className="text-2xl">{summary.avg_accuracy}%</strong><span className="text-[9px] uppercase tracking-widest text-white/70">accuracy</span></div></div></div></div>

    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4"><StatTile label="Students" value={summary.students}/><StatTile label="Active this week" value={summary.active_week}/><StatTile label="At-risk students" value={summary.at_risk} color={summary.at_risk ? "#ff6b7a" : undefined}/><StatTile label="Review backlog" value={data.pipeline.pending_review} color={data.pipeline.pending_review ? "#f5a623" : undefined}/></div>

    <Card><CardHeader><CardTitle>Key findings</CardTitle><CardDescription>Sorted by urgency, with a direct path to the affected quizzes or students.</CardDescription></CardHeader><CardContent><div className="grid gap-3 lg:grid-cols-2">{data.findings.map((finding, index) => { const tone = SEVERITY[finding.severity]; return <div key={`${finding.title}-${index}`} className="rounded-xl border bg-card p-4" style={{ borderLeft: `4px solid ${tone.color}` }}><div className="flex items-start justify-between gap-3"><div><span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${tone.chip}`}>{tone.label}</span><h3 className="mt-2 font-semibold">{finding.title}</h3></div>{finding.action_type && <button type="button" onClick={() => findingAction(finding)} className="shrink-0 text-sm font-semibold text-primary hover:underline">{finding.action_label ?? "View"} ↗</button>}</div><p className="mt-1 text-sm text-muted-foreground">{finding.detail}</p><p className="mt-3 rounded-lg bg-muted px-3 py-2 text-sm"><strong className="text-primary">Next:</strong> {finding.action}</p></div>; })}</div></CardContent></Card>

    <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
      <Card><CardHeader><CardTitle>Quiz activity</CardTitle><CardDescription>Fourteen-day engagement with a week-over-week comparison.</CardDescription></CardHeader><CardContent><div className="mb-5 grid gap-3 sm:grid-cols-3"><Metric label="Attempts this week" value={trend.attempts_last7}/><Metric label="Compared with last week" value={`${trendUp ? "↑" : "↓"} ${trend.delta > 0 ? "+" : ""}${trend.delta} (${trendPct > 0 ? "+" : ""}${trendPct}%)`} color={trendUp ? "text-emerald-600" : "text-rose-600"}/><Metric label="Active students this week" value={summary.active_week}/></div><div className="h-52"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data.activity} margin={{ top: 8, right: 12, bottom: 0, left: -20 }}><defs><linearGradient id="activityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={BRAND} stopOpacity={.3}/><stop offset="100%" stopColor={BRAND} stopOpacity={0}/></linearGradient></defs><XAxis dataKey="date" tick={{ fontSize: 11, fill: "#7c817d" }}/><YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#7c817d" }}/><Tooltip/><Area type="monotone" dataKey="attempts" stroke={BRAND} strokeWidth={2.5} fill="url(#activityFill)" dot={{ r: 2.5, fill: BRAND }}/></AreaChart></ResponsiveContainer></div><div className="mt-5 space-y-3 border-t pt-4">{[["Last 7 days", trend.attempts_last7, BRAND], ["Previous 7 days", trend.attempts_prev7, "#94a3b8"]].map(([label, value, color]) => <div key={String(label)} className="grid grid-cols-[110px_1fr_auto] items-center gap-3 text-sm"><span className="text-muted-foreground">{label}</span><div className="h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full" style={{ width: `${Number(value) / maxWeek * 100}%`, backgroundColor: String(color) }}/></div><strong>{value}</strong></div>)}</div></CardContent></Card>
      <Card><CardHeader><CardTitle>Students needing help</CardTitle><CardDescription>Average accuracy below 40%.</CardDescription></CardHeader><CardContent>{data.at_risk_students.length === 0 ? <p className="text-sm text-muted-foreground">No struggling students right now.</p> : <div className="flex flex-col gap-2">{data.at_risk_students.slice(0, 5).map((student) => <button key={student.student_id} type="button" onClick={() => { setSelectedStudent(student); setAtRiskOpen(true); }} className="grid grid-cols-[1fr_auto] gap-2 rounded-xl border p-3 text-left hover:bg-accent"><div className="min-w-0"><p className="truncate font-semibold">{student.name}</p><p className="truncate text-xs text-muted-foreground">Worst: {student.worst_quiz?.title ?? "No quiz data"} {student.worst_quiz ? `(${student.worst_quiz.accuracy}%)` : ""}</p><p className="mt-1 text-xs text-muted-foreground">{student.attempts} attempt{student.attempts === 1 ? "" : "s"}</p></div><strong className="text-rose-600">{student.accuracy}% →</strong></button>)}<button type="button" onClick={() => { setSelectedStudent(null); setAtRiskOpen(true); }} className="mt-2 text-left text-sm font-semibold text-primary hover:underline">View all {data.at_risk_students.length} at-risk students ↗</button></div>}</CardContent></Card>
    </div>

    <CourseTable courses={sortedCourses} sort={courseSort} onSort={toggleCourseSort} onOpen={(course) => setDrilldown({ type: "course", id: course.course_id, name: course.name })}/>

    <Card><CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between"><div><CardTitle>Teacher performance</CardTitle><CardDescription>Bar length shows attempts; color shows student accuracy.</CardDescription></div><select value={teacherSort} onChange={(event) => setTeacherSort(event.target.value as TeacherSort)} className="h-10 rounded-lg border bg-background px-3 text-sm"><option value="attempts">Sort: Attempts</option><option value="accuracy">Sort: Accuracy</option><option value="last_active">Sort: Last activity</option></select></CardHeader><CardContent className="space-y-3">{activeTeachers.map((teacher) => <TeacherRow key={teacher.teacher_id} teacher={teacher} maxAttempts={maxAttempts} onClick={() => setDrilldown({ type: "teacher", id: teacher.teacher_id, name: teacher.name })}/>) }{inactiveTeachers.length > 0 && <div className="border-t pt-3"><button type="button" onClick={() => setShowInactive((value) => !value)} className="flex w-full items-center justify-between rounded-lg px-2 py-2 text-sm font-semibold hover:bg-accent"><span>Inactive teachers</span><span className="text-muted-foreground">{inactiveTeachers.length} {showInactive ? "▲" : "▼"}</span></button>{showInactive && <div className="mt-2 space-y-2">{inactiveTeachers.map((teacher) => <TeacherRow key={teacher.teacher_id} teacher={teacher} maxAttempts={maxAttempts} onClick={() => setDrilldown({ type: "teacher", id: teacher.teacher_id, name: teacher.name })}/>)}</div>}</div>}</CardContent></Card>

    {drilldown && <QuizDrilldownModal title={`${drilldown.name} quizzes`} description={`${drilldown.type === "course" ? "Course" : "Teacher"} quizzes sorted by attempts, then lowest accuracy.`} quizzes={drilldownQuizzes} onClose={() => setDrilldown(null)} onSelect={(quiz) => { setDrilldown(null); setSelectedQuiz(quiz); }}/>}
    {pendingOpen && <QuizDrilldownModal title="Quizzes awaiting review" description="Quizzes with pending or needs-edit questions, highest backlog first." quizzes={pendingQuizzes} onClose={() => setPendingOpen(false)} onSelect={(quiz) => { setPendingOpen(false); setSelectedQuiz(quiz); }}/>}
    {atRiskOpen && <StudentPerformanceModal students={data.at_risk_students} initialStudent={selectedStudent} onClose={() => { setAtRiskOpen(false); setSelectedStudent(null); }}/>}
    {selectedQuiz && <QuizPerformanceModal quiz={selectedQuiz} onClose={() => setSelectedQuiz(null)}/>}
  </div>;
}

function Metric({ label, value, color = "text-foreground" }: { label: string; value: number | string; color?: string }) { return <div className="rounded-xl bg-secondary/40 p-4"><strong className={`text-xl ${color}`}>{value}</strong><p className="text-xs text-muted-foreground">{label}</p></div>; }

function TeacherRow({ teacher, maxAttempts, onClick }: { teacher: Teacher; maxAttempts: number; onClick: () => void }) {
  const color = teacher.attempts ? accuracyColor(teacher.accuracy) : "#94a3b8";
  return <button type="button" onClick={onClick} className="w-full rounded-xl border p-4 text-left transition hover:border-primary/35 hover:bg-accent"><div className="flex flex-wrap items-start justify-between gap-3"><div className="flex items-center gap-3"><span className="h-3 w-3 rounded-full" style={{ backgroundColor: color }}/><div><p className="font-semibold">{teacher.name}</p><p className="text-xs text-muted-foreground">Last active: {relativeDate(teacher.last_quiz_created)}</p></div></div><span className="text-sm font-semibold text-primary">View quizzes →</span></div><div className="mt-3 h-2.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full" style={{ width: `${teacher.attempts / maxAttempts * 100}%`, backgroundColor: color }}/></div><div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground"><span>{teacher.quiz_sets} sets</span><span>{teacher.published} published</span><span>{teacher.attempts} attempts</span><strong style={{ color }}>{teacher.attempts ? `${teacher.accuracy}% accuracy` : "No attempts"}</strong></div></button>;
}

function CourseTable({ courses, sort, onSort, onOpen }: { courses: Course[]; sort: { key: CourseSort; direction: "asc" | "desc" }; onSort: (key: CourseSort) => void; onOpen: (course: Course) => void }) {
  const headings: [CourseSort, string][] = [["name", "Course"], ["students", "Students"], ["published", "Published"], ["pending_review", "Pending review"], ["attempts", "Attempts"], ["accuracy", "Accuracy"]];
  return <Card><CardHeader><CardTitle>Course performance</CardTitle><CardDescription>Click any row to inspect its quizzes. Select a heading to sort.</CardDescription></CardHeader><CardContent>{courses.length === 0 ? <p className="text-sm text-muted-foreground">No courses yet.</p> : <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead><tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">{headings.map(([key, label]) => <th key={key} className={`px-3 py-3 font-medium ${key !== "name" ? "text-right" : ""}`}><button type="button" onClick={() => onSort(key)} className="hover:text-foreground">{label} {sort.key === key ? (sort.direction === "desc" ? "↓" : "↑") : "↕"}</button></th>)}<th className="px-3 py-3 text-right font-medium">Action</th></tr></thead><tbody>{courses.map((course) => <tr key={course.course_id} tabIndex={0} className="cursor-pointer border-b hover:bg-accent focus:bg-accent focus:outline-none last:border-0" onClick={() => onOpen(course)} onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && onOpen(course)}><td className="px-3 py-3 font-semibold">{course.name}</td><td className="px-3 py-3 text-right text-muted-foreground">{course.students}</td><td className="px-3 py-3 text-right text-muted-foreground">{course.published}</td><td className="px-3 py-3 text-right">{course.pending_review ? <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-700">{course.pending_review} pending</span> : <span className="text-muted-foreground">0</span>}</td><td className="px-3 py-3 text-right text-muted-foreground">{course.attempts}</td><td className="px-3 py-3 text-right font-semibold" style={{ color: course.attempts ? accuracyColor(course.accuracy) : "#94a3b8" }}>{course.attempts ? `${course.accuracy}%` : "—"}</td><td className="px-3 py-3 text-right font-semibold text-primary">View →</td></tr>)}</tbody></table></div>}</CardContent></Card>;
}
