"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { BookOpen, Check, ChevronDown, Copy, Eye, EyeOff, Pencil, Sparkles, Trash, Users, X } from "@/components/ui/icons";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import {
  AdminUser,
  CourseRoster,
  Subject,
  TeacherCourse,
  createTeacher,
  deleteUser,
  getTeacherSubjects,
  listCourseStudents,
  listTeacherCourses,
  resetTeacherTemporaryPassword,
  updateTeacher,
} from "@/lib/api";
import { useCourses, useInstitutionUsers } from "@/lib/staff-queries";
import { useSessionStorageState } from "@/lib/use-session-storage-state";
import {
  generateTemporaryPassword,
  validTemporaryPassword,
} from "@/lib/temporary-password";

const TEACHERS_PER_PAGE = 12;
const TEACHER_DRAFT_STORAGE_KEY = "institution-users-teacher-draft";

type TemporaryCredential = { email: string; password: string };
type Notice = { type: "success" | "error"; message: string };

function initials(text: string): string {
  return (
    text
      .split(/\s+/)
      .slice(0, 2)
      .map((w) => w[0])
      .join("")
      .toUpperCase() || "?"
  );
}

function subjectsByLevel(subjects: Subject[]): Array<[string, Subject[]]> {
  const groups = new Map<string, Subject[]>();
  for (const subject of subjects) {
    const level = subject.level_name?.trim() || "Custom subjects";
    groups.set(level, [...(groups.get(level) ?? []), subject]);
  }
  return Array.from(groups.entries());
}

export default function UsersPage() {
  const [query, setQuery] = useSessionStorageState(
    "institution-users-query",
    "",
    (value): value is string => typeof value === "string",
  );
  const [page, setPage] = useSessionStorageState(
    "institution-users-page",
    1,
    (value): value is number =>
      typeof value === "number" && Number.isInteger(value) && value > 0,
  );
  const teachersQuery = useInstitutionUsers(page, query);
  const coursesQuery = useCourses();
  const directory = teachersQuery.data ?? null;
  const teachers = directory?.items ?? null;
  const courses = coursesQuery.data ?? [];
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    course_id: "",
    level_id: "",
    subject_ids: [] as string[],
  });
  const [formHydrated, setFormHydrated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const [confirmDel, setConfirmDel] = useState<AdminUser | null>(null);
  const [manageTeacher, setManageTeacher] = useState<AdminUser | null>(null);
  const [editIdentity, setEditIdentity] = useState({ full_name: "", email: "" });
  const [assignedSubjects, setAssignedSubjects] = useState<Set<string>>(new Set());
  const [loadingSubjects, setLoadingSubjects] = useState(false);
  const [savingSubjects, setSavingSubjects] = useState(false);
  const [assignmentError, setAssignmentError] = useState<string | null>(null);
  const [expandedTeacherId, setExpandedTeacherId] = useState<string | null>(null);
  const [expandedCourseId, setExpandedCourseId] = useState<string | null>(null);
  const [teacherCourses, setTeacherCourses] = useState<Record<string, TeacherCourse[]>>({});
  const [courseRosters, setCourseRosters] = useState<Record<string, CourseRoster>>({});
  const [loadingTeacherId, setLoadingTeacherId] = useState<string | null>(null);
  const [loadingCourseId, setLoadingCourseId] = useState<string | null>(null);
  const [teacherCourseError, setTeacherCourseError] = useState<string | null>(null);
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [temporaryCredentials, setTemporaryCredentials] = useState<Record<string, TemporaryCredential>>({});
  const [copiedTeacherId, setCopiedTeacherId] = useState<string | null>(null);
  const [credentialResetTeacher, setCredentialResetTeacher] = useState<AdminUser | null>(null);
  const [resettingCredential, setResettingCredential] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const loadError = error ?? teachersQuery.error?.message ?? coursesQuery.error?.message ?? null;

  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(TEACHER_DRAFT_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved) as Record<string, unknown>;
        setForm((current) => ({
          ...current,
          full_name: typeof parsed.full_name === "string" ? parsed.full_name : "",
          email: typeof parsed.email === "string" ? parsed.email : "",
          course_id: typeof parsed.course_id === "string" ? parsed.course_id : "",
          level_id: typeof parsed.level_id === "string" ? parsed.level_id : "",
          subject_ids: Array.isArray(parsed.subject_ids)
            ? parsed.subject_ids.filter(
                (value): value is string => typeof value === "string",
              )
            : [],
        }));
      }
    } catch {
      // Keep the blank form when the saved draft is invalid or unavailable.
    } finally {
      setFormHydrated(true);
    }
  }, []);

  useEffect(() => {
    if (!formHydrated) return;
    try {
      window.sessionStorage.setItem(
        TEACHER_DRAFT_STORAGE_KEY,
        JSON.stringify({
          full_name: form.full_name,
          email: form.email,
          course_id: form.course_id,
          level_id: form.level_id,
          subject_ids: form.subject_ids,
        }),
      );
    } catch {
      // The form still works if browser storage is unavailable.
    }
  }, [
    form.course_id,
    form.email,
    form.full_name,
    form.level_id,
    form.subject_ids,
    formHydrated,
  ]);

  const selectedCourse = courses.find((course) => course.id === form.course_id);
  const selectedCourseLevels = selectedCourse
    ? subjectsByLevel(selectedCourse.subjects).map(([name, subjects]) => ({
        id: subjects[0]?.catalog_level_id ?? "custom",
        name,
        subjects,
      }))
    : [];
  const selectedLevel = selectedCourseLevels.find((level) => level.id === form.level_id);

  function showNotice(type: Notice["type"], message: string) {
    setNotice({ type, message });
    window.setTimeout(() => {
      setNotice((current) => current?.message === message ? null : current);
    }, 4000);
  }

  const total = directory?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / TEACHERS_PER_PAGE));
  const currentPage = Math.min(page, totalPages);
  const pageUsers = teachers ?? [];
  const firstResult = total
    ? (currentPage - 1) * TEACHERS_PER_PAGE + 1
    : 0;
  const lastResult = Math.min(currentPage * TEACHERS_PER_PAGE, total);

  async function add() {
    setBusy(true);
    setError(null);
    const submittedEmail = form.email;
    const submittedPassword = form.password;
    try {
      const created = await createTeacher({
        full_name: form.full_name,
        email: form.email,
        password: form.password,
        course_id: form.course_id,
        subject_ids: form.subject_ids,
      });
      setTemporaryCredentials((current) => ({
        ...current,
        [created.id]: { email: submittedEmail, password: submittedPassword },
      }));
      setForm({ full_name: "", email: "", password: "", course_id: "", level_id: "", subject_ids: [] });
      setPage(1);
      await teachersQuery.mutate();
      showNotice("success", "Teacher added successfully.");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to add teacher";
      setError(message);
      showNotice("error", message);
    } finally {
      setBusy(false);
    }
  }

  function generatePassword() {
    setForm((current) => ({ ...current, password: generateTemporaryPassword() }));
    setShowPw(true);
  }

  async function copyTeacherLogin(teacher: AdminUser) {
    const credential = temporaryCredentials[teacher.id];
    if (!credential) {
      setCredentialResetTeacher(teacher);
      return;
    }
    try {
      await navigator.clipboard.writeText(
        `Email: ${credential.email}\nTemporary password: ${credential.password}`,
      );
      setCopiedTeacherId(teacher.id);
      window.setTimeout(() => setCopiedTeacherId(null), 2000);
    } catch {
      showNotice("error", "Could not copy the teacher login. Please copy it manually.");
    }
  }

  async function resetAndCopyTeacherLogin() {
    if (!credentialResetTeacher) return;
    setResettingCredential(true);
    const credential: TemporaryCredential = {
      email: credentialResetTeacher.email || "",
      password: generateTemporaryPassword(),
    };
    try {
      await resetTeacherTemporaryPassword(
        credentialResetTeacher.id,
        credential.password,
      );
      setTemporaryCredentials((current) => ({
        ...current,
        [credentialResetTeacher.id]: credential,
      }));
    } catch (e) {
      showNotice(
        "error",
        e instanceof Error ? e.message : "Could not generate a new login.",
      );
      setResettingCredential(false);
      return;
    }

    const teacherId = credentialResetTeacher.id;
    setCredentialResetTeacher(null);
    setResettingCredential(false);
    try {
      await navigator.clipboard.writeText(
        `Email: ${credential.email}\nTemporary password: ${credential.password}`,
      );
      setCopiedTeacherId(teacherId);
      showNotice("success", "New temporary login generated and copied.");
      window.setTimeout(() => setCopiedTeacherId(null), 2000);
    } catch {
      showNotice(
        "error",
        "New login generated. Click Copy login again to copy it.",
      );
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError(null);
    try {
      await deleteUser(id);
      setConfirmDel(null);
      await teachersQuery.mutate();
      showNotice("success", "Teacher removed successfully.");
    } catch (e) {
      showNotice(
        "error",
        e instanceof Error ? e.message : "Failed to remove teacher.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function toggleTeacher(teacherId: string) {
    if (expandedTeacherId === teacherId) {
      setExpandedTeacherId(null);
      setExpandedCourseId(null);
      return;
    }
    setExpandedTeacherId(teacherId);
    setExpandedCourseId(null);
    setTeacherCourseError(null);
    if (teacherCourses[teacherId]) return;
    setLoadingTeacherId(teacherId);
    try {
      const result = await listTeacherCourses(teacherId);
      setTeacherCourses((current) => ({ ...current, [teacherId]: result }));
    } catch (e) {
      setTeacherCourseError(e instanceof Error ? e.message : "Failed to load courses.");
    } finally {
      setLoadingTeacherId(null);
    }
  }

  async function toggleCourse(courseId: string) {
    if (expandedCourseId === courseId) {
      setExpandedCourseId(null);
      return;
    }
    setExpandedCourseId(courseId);
    setRosterError(null);
    if (courseRosters[courseId]) return;
    setLoadingCourseId(courseId);
    try {
      const result = await listCourseStudents(courseId);
      setCourseRosters((current) => ({ ...current, [courseId]: result }));
    } catch (e) {
      setRosterError(e instanceof Error ? e.message : "Failed to load students.");
    } finally {
      setLoadingCourseId(null);
    }
  }

  async function openSubjectAssignments(teacher: AdminUser) {
    setManageTeacher(teacher);
    setEditIdentity({
      full_name: teacher.full_name || "",
      email: teacher.email || "",
    });
    setAssignedSubjects(new Set());
    setAssignmentError(null);
    setLoadingSubjects(true);
    try {
      const result = await getTeacherSubjects(teacher.id);
      setAssignedSubjects(new Set(result.subject_ids));
    } catch (e) {
      setAssignmentError(
        e instanceof Error ? e.message : "Failed to load subject assignments.",
      );
    } finally {
      setLoadingSubjects(false);
    }
  }

  function toggleSubject(subjectId: string) {
    setAssignedSubjects((current) => {
      const next = new Set(current);
      if (next.has(subjectId)) next.delete(subjectId);
      else next.add(subjectId);
      return next;
    });
  }

  async function saveSubjectAssignments() {
    if (!manageTeacher) return;
    setSavingSubjects(true);
    setAssignmentError(null);
    try {
      await updateTeacher(manageTeacher.id, {
        full_name: editIdentity.full_name,
        email: editIdentity.email,
        subject_ids: Array.from(assignedSubjects),
      });
      setTeacherCourses((current) => {
        const next = { ...current };
        delete next[manageTeacher.id];
        return next;
      });
      setExpandedTeacherId(null);
      setExpandedCourseId(null);
      setManageTeacher(null);
      await teachersQuery.mutate();
      showNotice("success", "Teacher updated successfully.");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to update teacher.";
      setAssignmentError(message);
      showNotice("error", message);
    } finally {
      setSavingSubjects(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {notice && (
        <div
          role={notice.type === "error" ? "alert" : "status"}
          aria-live="polite"
          className={`fixed right-4 top-20 z-[60] flex max-w-sm items-center gap-3 rounded-xl border px-4 py-3 shadow-xl ${
            notice.type === "success"
              ? "border-primary/25 bg-primary text-primary-foreground"
              : "border-destructive/25 bg-destructive text-destructive-foreground"
          }`}
        >
          {notice.type === "success" ? <Check size={18} /> : <X size={18} />}
          <span className="text-sm font-semibold">{notice.message}</span>
          <button type="button" aria-label="Dismiss notification" onClick={() => setNotice(null)}>
            <X size={16} />
          </button>
        </div>
      )}
      <PageHeader
        title="Teachers"
        description="Add teachers, assign their subjects, and view course student rosters."
        actions={
          <div className="flex items-center gap-2">
            <Link
              href="#teacher-directory"
              className="rounded-lg border border-input bg-card px-3 py-2 text-sm font-medium hover:bg-accent"
            >
              View teachers
            </Link>
            <Link
              href="#add-teacher"
              className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Add teacher
            </Link>
          </div>
        }
      />

      <Card id="add-teacher" className="animate-rise scroll-mt-24">
        <CardHeader>
          <CardTitle>Add teacher</CardTitle>
          <CardDescription>
            Create a teacher account with a temporary password and assign teaching subjects.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Input autoComplete="name" placeholder="Teacher name" value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
          <Input autoComplete="email" placeholder="teacher@example.com" type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
          <label className="flex flex-col gap-1.5 text-sm font-medium text-foreground">
            Course
            <select
              value={form.course_id}
              onChange={(event) => setForm((current) => ({
                ...current,
                course_id: event.target.value,
                level_id: "",
                subject_ids: [],
              }))}
              className="h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">Select a course</option>
              {courses.map((course) => (
                <option key={course.id} value={course.id}>{course.name}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5 text-sm font-medium text-foreground">
            Level
            <select
              value={form.level_id}
              disabled={!selectedCourse || selectedCourseLevels.length === 0}
              onChange={(event) => setForm((current) => ({
                ...current,
                level_id: event.target.value,
                subject_ids: [],
              }))}
              className="h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring disabled:opacity-60"
            >
              <option value="">Select a level</option>
              {selectedCourseLevels.map((level) => (
                <option key={level.id} value={level.id}>{level.name}</option>
              ))}
            </select>
          </label>
          <fieldset className="rounded-xl border border-border p-3">
            <legend className="px-1 text-sm font-medium text-foreground">Subjects</legend>
            {!selectedCourse ? (
              <p className="text-sm text-muted-foreground">Select a course first.</p>
            ) : selectedCourse.subjects.length === 0 ? (
              <p className="text-sm text-muted-foreground">This course has no subjects yet.</p>
            ) : !selectedLevel ? (
              <p className="text-sm text-muted-foreground">Select a level next.</p>
            ) : (
              <div className="flex max-h-48 flex-wrap gap-2 overflow-y-auto">
                {selectedLevel.subjects.map((subject) => {
                  const checked = form.subject_ids.includes(subject.id);
                  return (
                    <label key={subject.id} className={`cursor-pointer rounded-full border px-3 py-1.5 text-xs font-semibold transition ${checked ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:border-primary/40"}`}>
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
                        onChange={() => setForm((current) => ({
                          ...current,
                          subject_ids: checked
                            ? current.subject_ids.filter((id) => id !== subject.id)
                            : [...current.subject_ids, subject.id],
                        }))}
                      />
                      {subject.name}
                    </label>
                  );
                })}
              </div>
            )}
          </fieldset>
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Input
                placeholder="Temporary password"
                autoComplete="new-password"
                type={showPw ? "text" : "password"}
                className="pr-10"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              />
              <button
                type="button"
                onClick={() => setShowPw((v) => !v)}
                aria-label={showPw ? "Hide password" : "Show password"}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
              >
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            <Button type="button" variant="outline" onClick={generatePassword}>
              <Sparkles size={15} className="mr-1.5" />
              Generate
            </Button>
          </div>
          <p className="text-xs text-muted-foreground sm:col-span-2">Use at least 12 characters with uppercase, lowercase, and a number.</p>
          <Button disabled={busy || !form.full_name.trim() || !form.email.trim() || !validTemporaryPassword(form.password) || !form.course_id || !form.level_id || form.subject_ids.length === 0} onClick={add}>
            {busy ? "Adding…" : "Add teacher"}
          </Button>
          {loadError && (
            <div className="sm:col-span-2">
              <ErrorCard message={loadError} onRetry={() => void Promise.all([teachersQuery.mutate(), coursesQuery.mutate()])} />
            </div>
          )}
        </CardContent>
      </Card>

      <section id="teacher-directory" className="flex scroll-mt-24 flex-col gap-4" aria-labelledby="teacher-list-title">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 id="teacher-list-title" className="text-xl font-bold text-foreground">
              Teaching staff{directory ? ` (${directory.total})` : ""}
            </h2>
            <p className="text-sm text-muted-foreground">
              Select a teacher to view courses, then select a course to view enrolled students.
            </p>
          </div>
          <Input
            type="search"
            value={query}
            onChange={(event) => { setQuery(event.target.value); setPage(1); }}
            placeholder="Search teacher names"
            aria-label="Search teacher names"
            className="sm:max-w-sm"
          />
        </div>

        {teachers === null ? (
          <Card><CardContent className="pt-6"><SkeletonList rows={4} /></CardContent></Card>
        ) : teachers.length === 0 ? (
          <Card><CardContent className="pt-6"><EmptyState icon={<Users />} title={query ? "No matching teachers" : "No teachers yet"} message={query ? "Try a different teacher name." : "Add the first teacher using the form above."} /></CardContent></Card>
        ) : (
          <>
            <p className="text-xs text-muted-foreground" aria-live="polite">
              Showing {firstResult}–{lastResult} of {total}
            </p>
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {pageUsers.map((teacher) => {
                const name = teacher.full_name || teacher.email || "Unnamed teacher";
                const isExpanded = expandedTeacherId === teacher.id;
                const assignedCourses = teacherCourses[teacher.id];
                return (
                  <Card key={teacher.id} className="overflow-hidden transition-shadow hover:shadow-md">
                    <CardContent className="p-0">
                      <div className="flex items-start gap-3 p-5">
                        <button
                          type="button"
                          className="flex min-w-0 flex-1 items-start gap-3 text-left"
                          aria-expanded={isExpanded}
                          aria-controls={`teacher-${teacher.id}-courses`}
                          onClick={() => void toggleTeacher(teacher.id)}
                        >
                          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-sm font-bold text-primary">{initials(name)}</span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-bold text-foreground">{name}</span>
                            <span className="block truncate text-sm text-muted-foreground">{teacher.email || "Email unavailable"}</span>
                            <span className="mt-2 block text-xs text-muted-foreground">
                              {teacher.courses.length} course{teacher.courses.length === 1 ? "" : "s"} · {teacher.subject_count} subject{teacher.subject_count === 1 ? "" : "s"}
                            </span>
                          </span>
                          <ChevronDown size={18} className={`mt-1 shrink-0 transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                        </button>
                        <div className="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:items-center">
                          <Button size="sm" variant="outline" asChild>
                            <Link href={`/dashboard/institution-admin/quizzes?teacher=${encodeURIComponent(teacher.id)}`}>
                              Performance
                            </Link>
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            title={temporaryCredentials[teacher.id] ? "Copy email and temporary password" : "Generate a new temporary password and copy the login"}
                            onClick={() => void copyTeacherLogin(teacher)}
                          >
                            <Copy size={14} className="mr-1.5" />
                            {copiedTeacherId === teacher.id ? "Copied" : "Copy login"}
                          </Button>
                          <button
                            type="button"
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-input text-muted-foreground transition hover:bg-accent hover:text-primary"
                            aria-label={`Edit ${name}`}
                            title="Edit teacher"
                            onClick={() => void openSubjectAssignments(teacher)}
                          >
                            <Pencil size={16} />
                          </button>
                          <button type="button" className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-destructive/10 hover:text-destructive" disabled={busy} aria-label={`Remove ${name}`} onClick={() => setConfirmDel(teacher)}><Trash size={16} /></button>
                        </div>
                      </div>

                      {isExpanded && (
                        <div id={`teacher-${teacher.id}-courses`} className="border-t bg-secondary/20 p-4">
                          {loadingTeacherId === teacher.id ? (
                            <SkeletonList rows={2} />
                          ) : teacherCourseError ? (
                            <ErrorCard message={teacherCourseError} />
                          ) : !assignedCourses?.length ? (
                            <EmptyState icon={<BookOpen />} title="No courses assigned" message="Use Edit to give this teacher access to course subjects." />
                          ) : (
                            <div className="flex flex-col gap-2">
                              {assignedCourses.map((course) => {
                                const courseExpanded = expandedCourseId === course.id;
                                const roster = courseRosters[course.id];
                                return (
                                  <div key={course.id} className="overflow-hidden rounded-xl border bg-card">
                                    <button type="button" className="flex w-full items-center gap-3 p-3 text-left hover:bg-accent" aria-expanded={courseExpanded} aria-controls={`course-${course.id}-students`} onClick={() => void toggleCourse(course.id)}>
                                      <BookOpen size={18} className="shrink-0 text-primary" />
                                      <span className="min-w-0 flex-1">
                                        <span className="block truncate text-sm font-semibold">{course.name}</span>
                                        <span className="block truncate text-xs text-muted-foreground">{course.subjects.map((subject) => subject.name).join(", ")}</span>
                                      </span>
                                      <span className="shrink-0 rounded-full bg-primary/10 px-2 py-1 text-xs font-semibold text-primary">{course.student_count} student{course.student_count === 1 ? "" : "s"}</span>
                                      <ChevronDown size={16} className={`shrink-0 transition-transform ${courseExpanded ? "rotate-180" : ""}`} />
                                    </button>
                                    {courseExpanded && (
                                      <div id={`course-${course.id}-students`} className="border-t p-3">
                                        {loadingCourseId === course.id ? (
                                          <SkeletonList rows={3} />
                                        ) : rosterError ? (
                                          <ErrorCard message={rosterError} />
                                        ) : !roster?.students.length ? (
                                          <p className="py-3 text-center text-sm text-muted-foreground">No students are enrolled in this course yet.</p>
                                        ) : (
                                          <ul className="max-h-64 divide-y overflow-y-auto">
                                            {roster.students.map((student) => {
                                              const studentName = student.full_name || student.email || "Unnamed student";
                                              return <li key={student.id} className="flex items-center gap-3 py-2.5"><span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-bold text-primary">{initials(studentName)}</span><span className="min-w-0"><span className="block truncate text-sm font-medium">{studentName}</span><span className="block truncate text-xs text-muted-foreground">{student.email || "Email unavailable"}</span></span></li>;
                                            })}
                                          </ul>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
            {total > TEACHERS_PER_PAGE && (
              <div className="flex items-center justify-between border-t pt-4">
                <Button variant="outline" size="sm" disabled={currentPage === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</Button>
                <span className="text-sm text-muted-foreground">Page {currentPage} of {totalPages}</span>
                <Button variant="outline" size="sm" disabled={currentPage === totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>Next</Button>
              </div>
            )}
          </>
        )}
      </section>

      {manageTeacher && (
        <Dialog
          onClose={() => !savingSubjects && setManageTeacher(null)}
          ariaLabelledBy="teacher-edit-title"
          closeOnBackdrop={!savingSubjects}
          contentClassName="animate-rise flex max-h-[90vh] w-full max-w-lg flex-col rounded-2xl border border-border bg-card shadow-2xl"
        >
          <div>
            <div className="flex items-start justify-between gap-3 border-b p-5">
              <div>
                <h3 id="teacher-edit-title" className="text-base font-bold text-foreground">
                  Edit teacher
                </h3>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Update the teacher&apos;s name, email, courses, and subjects.
                </p>
              </div>
              <button
                type="button"
                onClick={() => !savingSubjects && setManageTeacher(null)}
                aria-label="Close teacher editor"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                <X size={18} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-5">
              {loadingSubjects ? (
                <SkeletonList rows={4} />
              ) : courses.length === 0 ? (
                <EmptyState
                  title="No subjects available"
                  message="Create a course and its subjects before assigning them to a teacher."
                />
              ) : (
                <div className="flex flex-col gap-4">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="flex flex-col gap-1.5 text-sm font-medium text-foreground">
                      Name
                      <Input
                        autoComplete="name"
                        value={editIdentity.full_name}
                        onChange={(event) => setEditIdentity((current) => ({ ...current, full_name: event.target.value }))}
                      />
                    </label>
                    <label className="flex flex-col gap-1.5 text-sm font-medium text-foreground">
                      Email
                      <Input
                        autoComplete="email"
                        type="email"
                        value={editIdentity.email}
                        onChange={(event) => setEditIdentity((current) => ({ ...current, email: event.target.value }))}
                      />
                    </label>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Selecting subjects under a course assigns that course to the teacher.
                  </p>
                  {courses.map((course) => (
                    <div key={course.id}>
                      <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {course.name}
                      </div>
                      {course.subjects.length === 0 ? (
                        <p className="pl-1 text-xs text-muted-foreground">
                          No subjects in this course.
                        </p>
                      ) : (
                        <div className="flex flex-col gap-3">
                          {subjectsByLevel(course.subjects).map(([level, subjects]) => (
                            <div key={level} className="rounded-lg border border-border/70 p-2">
                              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                {level}
                              </p>
                              {subjects.map((subject) => (
                                <label
                                  key={subject.id}
                                  className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-accent"
                                >
                                  <input
                                    type="checkbox"
                                    checked={assignedSubjects.has(subject.id)}
                                    onChange={() => toggleSubject(subject.id)}
                                    className="h-4 w-4 rounded border-input accent-primary"
                                  />
                                  <span className="text-sm text-foreground">{subject.name}</span>
                                </label>
                              ))}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {assignmentError && (
                <div className="mt-3">
                  <ErrorCard message={assignmentError} />
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 border-t p-4">
              <button
                type="button"
                onClick={() => setManageTeacher(null)}
                disabled={savingSubjects}
                className="rounded-lg border border-input px-4 py-2 text-sm font-semibold text-foreground transition hover:bg-secondary disabled:opacity-50"
              >
                Cancel
              </button>
              <Button
                onClick={saveSubjectAssignments}
                disabled={savingSubjects || loadingSubjects || !editIdentity.full_name.trim() || !editIdentity.email.trim()}
              >
                {savingSubjects ? "Saving…" : "Save changes"}
              </Button>
            </div>
          </div>
        </Dialog>
      )}

      {confirmDel && (
        <Dialog
          onClose={() => !busy && setConfirmDel(null)}
          ariaLabel="Remove teacher"
          closeOnBackdrop={!busy}
          contentClassName="animate-rise w-full max-w-sm rounded-2xl border border-border bg-card p-6 shadow-2xl"
        >
          <div>
            <div className="mb-3 flex items-start justify-between gap-3">
              <h3 className="text-base font-bold text-foreground">Remove teacher</h3>
              <button
                onClick={() => !busy && setConfirmDel(null)}
                aria-label="Close"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                <X size={18} />
              </button>
            </div>
            <p className="text-sm text-muted-foreground">
              Remove{" "}
              <span className="font-semibold text-foreground">
                {confirmDel.full_name || confirmDel.email}
              </span>
              ? This cannot be undone.
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={() => setConfirmDel(null)}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-input px-4 py-2 text-sm font-semibold text-foreground transition hover:bg-secondary disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => remove(confirmDel.id)}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-destructive px-4 py-2 text-sm font-semibold text-destructive-foreground transition hover:opacity-90 disabled:opacity-50"
              >
                <Trash size={15} />
                {busy ? "Removing…" : "Remove"}
              </button>
            </div>
          </div>
        </Dialog>
      )}

      {credentialResetTeacher && (
        <Dialog
          onClose={() => !resettingCredential && setCredentialResetTeacher(null)}
          ariaLabelledBy="reset-login-title"
          closeOnBackdrop={!resettingCredential}
          contentClassName="animate-rise w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl"
        >
          <div>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 id="reset-login-title" className="text-base font-bold text-foreground">Generate a new login?</h3>
                <p className="mt-2 text-sm text-muted-foreground">
                  The original password cannot be retrieved after a refresh. This will replace the password for {credentialResetTeacher.full_name || credentialResetTeacher.email} and copy the new email and temporary password.
                </p>
              </div>
              <button type="button" aria-label="Close" disabled={resettingCredential} onClick={() => setCredentialResetTeacher(null)} className="text-muted-foreground hover:text-foreground disabled:opacity-50"><X size={18} /></button>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="outline" disabled={resettingCredential} onClick={() => setCredentialResetTeacher(null)}>Cancel</Button>
              <Button type="button" disabled={resettingCredential} onClick={() => void resetAndCopyTeacherLogin()}>
                {resettingCredential ? "Generating…" : "Generate and copy"}
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
