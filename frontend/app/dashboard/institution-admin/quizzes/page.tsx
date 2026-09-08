"use client";

import { useEffect, useMemo, useState } from "react";

import { FacultyAnalysisCard } from "@/components/institution-admin/faculty-analysis-card";
import { QuestionPaperButtons } from "@/components/shared/pdf-buttons";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { ChevronDown, Inbox, Users } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import {
  AdminQuizSet,
  TeacherAnalytics,
  getAdminQuizSets,
  getTeacherAnalytics,
} from "@/lib/api";

import { QuizPerformanceModal } from "./_components/quiz-performance-modal";

type SortKey =
  | "created_desc"
  | "created_asc"
  | "attempts_desc"
  | "attempts_asc"
  | "accuracy_desc"
  | "accuracy_asc"
  | "published_first";

const SORT_KEYS: SortKey[] = [
  "created_desc",
  "created_asc",
  "attempts_desc",
  "attempts_asc",
  "accuracy_desc",
  "accuracy_asc",
  "published_first",
];

const STATUS_TONE: Record<string, string> = {
  published: "bg-emerald-100 text-emerald-700",
  draft: "bg-amber-100 text-amber-700",
};

const SELECT_CLASS =
  "h-11 rounded-xl border border-input bg-background px-3 text-sm shadow-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20";

function health(quiz: AdminQuizSet) {
  if (quiz.review_status.pending + quiz.review_status.needs_edit > 0) {
    return {
      label: "Pending review",
      tone: "bg-amber-100 text-amber-800",
      icon: "⚠️",
    };
  }
  if (quiz.attempts_count === 0) {
    return {
      label: "No attempts",
      tone: "bg-rose-100 text-rose-700",
      icon: "●",
    };
  }
  if (quiz.attempts_count < 5) {
    return {
      label: "Low engagement",
      tone: "bg-amber-100 text-amber-800",
      icon: "●",
    };
  }
  return {
    label: "Active",
    tone: "bg-emerald-100 text-emerald-700",
    icon: "●",
  };
}

export default function AdminQuizzesPage() {
  const [rows, setRows] = useState<AdminQuizSet[] | null>(null);
  const [faculty, setFaculty] = useState<TeacherAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [teacherId, setTeacherId] = useState("");
  const [courseId, setCourseId] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState<SortKey>("created_desc");
  const [filtersReady, setFiltersReady] = useState(false);
  const [selectedQuiz, setSelectedQuiz] = useState<AdminQuizSet | null>(null);
  const [teacherRows, setTeacherRows] = useState<{
    teacherId: string;
    rows: AdminQuizSet[];
  } | null>(null);

  function load() {
    setError(null);
    Promise.all([getAdminQuizSets(), getTeacherAnalytics()])
      .then(([quizRows, teacherAnalytics]) => {
        setRows(quizRows);
        setFaculty(teacherAnalytics);
      })
      .catch((reason) => setError(reason.message));
  }

  useEffect(load, []);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setQuery(params.get("q") ?? "");
    setTeacherId(params.get("teacher") ?? "");
    setCourseId(params.get("course") ?? "");
    setStatus(params.get("status") ?? "");
    const requestedSort = params.get("sort");
    if (requestedSort && SORT_KEYS.includes(requestedSort as SortKey)) {
      setSort(requestedSort as SortKey);
    }
    setFiltersReady(true);
  }, []);
  useEffect(() => {
    if (!filtersReady) return;
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (teacherId) params.set("teacher", teacherId);
    if (courseId) params.set("course", courseId);
    if (status) params.set("status", status);
    if (sort !== "created_desc") params.set("sort", sort);
    const search = params.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${search ? `?${search}` : ""}`,
    );
  }, [courseId, filtersReady, query, sort, status, teacherId]);

  const selectedTeacher = useMemo(
    () => faculty?.teachers.find((teacher) => teacher.teacher_id === teacherId),
    [faculty, teacherId],
  );
  const sourceRows = useMemo(
    () =>
      teacherId && teacherRows?.teacherId === teacherId
        ? teacherRows.rows
        : (rows ?? []).filter((quiz) => !teacherId || quiz.teacher_id === teacherId),
    [rows, teacherId, teacherRows],
  );
  const courses = useMemo(() => {
    const options = new Map<string, string>();
    for (const row of sourceRows) {
      if (row.course_id) options.set(row.course_id, row.course || "Course");
    }
    return Array.from(options, ([id, name]) => ({ id, name })).sort((a, b) =>
      a.name.localeCompare(b.name),
    );
  }, [sourceRows]);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const result = sourceRows.filter((row) => {
      const matchesSearch =
        !normalized ||
        [row.title, row.course, row.subject]
          .filter(Boolean)
          .some((value) =>
            (value as string).toLowerCase().includes(normalized),
          );
      return (
        matchesSearch &&
        (!courseId || row.course_id === courseId) &&
        (!status || row.status === status)
      );
    });
    return result.sort((a, b) => {
      if (sort === "attempts_desc" || sort === "attempts_asc") {
        return (
          (a.attempts_count - b.attempts_count) *
          (sort === "attempts_asc" ? 1 : -1)
        );
      }
      if (sort === "accuracy_desc" || sort === "accuracy_asc") {
        return (
          (a.avg_accuracy - b.avg_accuracy) *
          (sort === "accuracy_asc" ? 1 : -1)
        );
      }
      if (sort === "published_first") {
        return Number(b.status === "published") - Number(a.status === "published");
      }
      const dates =
        new Date(a.created_at ?? 0).getTime() -
        new Date(b.created_at ?? 0).getTime();
      return dates * (sort === "created_asc" ? 1 : -1);
    });
  }, [courseId, query, sort, sourceRows, status]);

  function openTeacher(nextTeacherId: string) {
    setError(null);
    setTeacherId(nextTeacherId);
    setTeacherRows(null);
    setQuery("");
    setCourseId("");
    setStatus("");
    setSort("created_desc");
    getAdminQuizSets(nextTeacherId)
      .then((quizRows) =>
        setTeacherRows({ teacherId: nextTeacherId, rows: quizRows }),
      )
      .catch((reason) => setError(reason.message));
  }

  function backToFaculty() {
    setTeacherId("");
    setTeacherRows(null);
    setQuery("");
    setCourseId("");
    setStatus("");
    setSort("created_desc");
  }

  function clearQuizFilters() {
    setQuery("");
    setCourseId("");
    setStatus("");
    setSort("created_desc");
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={teacherId ? `${selectedTeacher?.teacher_name ?? "Faculty"} quizzes` : "Faculty quiz performance"}
        description={
          teacherId
            ? "Review this faculty member's quizzes, engagement, accuracy, and question health."
            : "Select a faculty member to review the quizzes they created and how students performed."
        }
      />
      {error && <ErrorCard message={error} onRetry={load} />}

      {!teacherId ? (
        faculty === null ? (
          <SkeletonList rows={4} />
        ) : faculty.teachers.length === 0 ? (
          <EmptyState
            icon={<Users />}
            title="No faculty yet"
            message="Faculty performance cards will appear after teachers are added."
          />
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {faculty.teachers.map((teacher) => (
              <FacultyAnalysisCard
                key={teacher.teacher_id}
                teacher={teacher}
                onOpen={() => openTeacher(teacher.teacher_id)}
              />
            ))}
          </div>
        )
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              onClick={backToFaculty}
              className="inline-flex items-center gap-2 text-sm font-semibold text-primary hover:underline"
            >
              <ChevronDown size={16} className="rotate-90" /> Back to all faculty
            </button>
            {selectedTeacher && (
              <span className="text-sm text-muted-foreground">
                {selectedTeacher.quiz_sets_created} quizzes · {selectedTeacher.quiz_sets_published} published · {selectedTeacher.total_attempts} attempts
              </span>
            )}
          </div>

          <Card className="animate-rise">
            <CardContent className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-[minmax(260px,1fr)_190px_170px_220px]">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search this faculty member's quizzes…"
                aria-label="Search faculty quizzes"
                className="h-11 rounded-xl border border-input bg-background px-4 text-sm shadow-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              />
              <select
                value={courseId}
                onChange={(event) => setCourseId(event.target.value)}
                aria-label="Filter by course"
                className={SELECT_CLASS}
              >
                <option value="">All courses</option>
                {courses.map((course) => (
                  <option key={course.id} value={course.id}>{course.name}</option>
                ))}
              </select>
              <select
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                aria-label="Filter by status"
                className={SELECT_CLASS}
              >
                <option value="">All statuses</option>
                <option value="published">Published</option>
                <option value="draft">Draft</option>
              </select>
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value as SortKey)}
                aria-label="Sort quizzes"
                className={SELECT_CLASS}
              >
                <option value="created_desc">Newest created</option>
                <option value="created_asc">Oldest created</option>
                <option value="attempts_desc">Most attempts</option>
                <option value="attempts_asc">Fewest attempts</option>
                <option value="accuracy_desc">Highest accuracy</option>
                <option value="accuracy_asc">Lowest accuracy</option>
                <option value="published_first">Published first</option>
              </select>
            </CardContent>
          </Card>

          <div className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
            <span>{filtered.length} of {sourceRows.length} quizzes</span>
            {(query || courseId || status || sort !== "created_desc") && (
              <button type="button" onClick={clearQuizFilters} className="font-semibold text-primary hover:underline">
                Clear filters
              </button>
            )}
          </div>

          {rows === null ? (
            <SkeletonList />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<Inbox />}
              title={sourceRows.length === 0 ? "No quizzes created" : "No matching quizzes"}
              message={
                sourceRows.length === 0
                  ? "This faculty member has not created a quiz yet."
                  : "Try changing or clearing the filters above."
              }
            />
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              {filtered.map((quiz) => {
                const state = health(quiz);
                const pending =
                  quiz.review_status.pending + quiz.review_status.needs_edit;
                return (
                  <Card
                    key={quiz.id}
                    role="button"
                    tabIndex={0}
                    className="animate-rise cursor-pointer overflow-hidden transition hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                    onClick={() => setSelectedQuiz(quiz)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedQuiz(quiz);
                      }
                    }}
                  >
                    <CardContent className="p-5">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <h2 className="truncate text-base font-bold text-foreground">{quiz.title}</h2>
                          <p className="mt-1 truncate text-sm text-muted-foreground">
                            {[quiz.course, quiz.subject].filter(Boolean).join(" · ") || "—"}
                          </p>
                        </div>
                        <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${STATUS_TONE[quiz.status] ?? "bg-muted text-muted-foreground"}`}>
                          {quiz.status}
                        </span>
                      </div>
                      <div className="mt-5 grid grid-cols-3 divide-x rounded-xl bg-secondary/35 py-3 text-center">
                        <div><div className="text-lg font-bold text-foreground">{quiz.attempts_count}</div><div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Attempts</div></div>
                        <div><div className="text-lg font-bold text-foreground">{quiz.attempts_count ? `${quiz.avg_accuracy}%` : "—"}</div><div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Accuracy</div></div>
                        <div><div className="text-lg font-bold text-foreground">{quiz.questions}</div><div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Questions</div></div>
                      </div>
                      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                        <div className="flex flex-wrap gap-2">
                          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${state.tone}`}><span className="mr-1">{state.icon}</span>{state.label}</span>
                          {pending > 0 && <span className="rounded-full bg-violet-100 px-2.5 py-1 text-xs font-semibold text-violet-700">{pending} awaiting review</span>}
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="hidden text-xs text-muted-foreground sm:inline">{quiz.created_at ? new Date(quiz.created_at).toLocaleDateString() : "—"}</span>
                          <div onClick={(event) => event.stopPropagation()}>
                            <QuestionPaperButtons quizSetId={quiz.id} title={quiz.title} meta={[quiz.course, quiz.subject].filter(Boolean).join(" · ")} compact />
                          </div>
                          <ChevronDown size={17} className="-rotate-90 text-muted-foreground" />
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </>
      )}

      {selectedQuiz && (
        <QuizPerformanceModal
          quiz={selectedQuiz}
          onClose={() => setSelectedQuiz(null)}
        />
      )}
    </div>
  );
}
