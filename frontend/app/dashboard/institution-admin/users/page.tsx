"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { Eye, EyeOff, Trash, Users, X } from "@/components/ui/icons";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import { statusLabel } from "@/lib/format";
import {
  AdminUser,
  Course,
  createUser,
  deleteUser,
  getTeacherSubjects,
  listCourses,
  listUsers,
  setTeacherSubjects,
} from "@/lib/api";

const selectClass =
  "h-9 rounded-md border border-input bg-transparent px-3 text-sm";
const USERS_PER_PAGE = 25;

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

export default function UsersPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    role: "student",
    course_id: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const [confirmDel, setConfirmDel] = useState<AdminUser | null>(null);
  const [manageTeacher, setManageTeacher] = useState<AdminUser | null>(null);
  const [assignedSubjects, setAssignedSubjects] = useState<Set<string>>(new Set());
  const [loadingSubjects, setLoadingSubjects] = useState(false);
  const [savingSubjects, setSavingSubjects] = useState(false);
  const [assignmentError, setAssignmentError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);

  const filteredUsers = useMemo(() => {
    if (!users) return [];
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return users;
    return users.filter((user) =>
      [user.full_name, user.email, user.role, ...user.courses]
        .some((value) => value?.toLowerCase().includes(normalizedQuery) ?? false),
    );
  }, [query, users]);
  const totalPages = Math.max(1, Math.ceil(filteredUsers.length / USERS_PER_PAGE));
  const currentPage = Math.min(page, totalPages);
  const pageUsers = filteredUsers.slice(
    (currentPage - 1) * USERS_PER_PAGE,
    currentPage * USERS_PER_PAGE,
  );
  const firstResult = filteredUsers.length
    ? (currentPage - 1) * USERS_PER_PAGE + 1
    : 0;
  const lastResult = Math.min(currentPage * USERS_PER_PAGE, filteredUsers.length);

  function refresh() {
    listUsers().then(setUsers).catch((e) => setError(e.message));
  }
  useEffect(() => {
    refresh();
    listCourses().then(setCourses).catch((e) => setError(e.message));
  }, []);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      await createUser({
        full_name: form.full_name,
        email: form.email,
        password: form.password,
        role: form.role as "teacher" | "student",
        course_id: form.course_id,
      });
      setForm({ full_name: "", email: "", password: "", role: "student", course_id: "" });
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add user");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError(null);
    try {
      await deleteUser(id);
      setConfirmDel(null);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove user");
    } finally {
      setBusy(false);
    }
  }

  async function openSubjectAssignments(teacher: AdminUser) {
    setManageTeacher(teacher);
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
      await setTeacherSubjects(manageTeacher.id, Array.from(assignedSubjects));
      setManageTeacher(null);
      refresh();
    } catch (e) {
      setAssignmentError(
        e instanceof Error ? e.message : "Failed to save subject assignments.",
      );
    } finally {
      setSavingSubjects(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Users"
        description="Create teacher and student accounts, assign courses, and manage access."
      />

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Add teacher or student</CardTitle>
          <CardDescription>
            Creates a ready-to-use account, enrolled in the chosen course.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Input placeholder="Full name" value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
          <Input placeholder="Email" type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
          <div className="relative">
            <Input
              placeholder="Temporary password"
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
          <select className={selectClass} value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
            <option value="student">Student</option>
            <option value="teacher">Teacher</option>
          </select>
          <select className={selectClass} value={form.course_id} onChange={(e) => setForm((f) => ({ ...f, course_id: e.target.value }))}>
            <option value="">Select course</option>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <Button disabled={busy || !form.full_name || !form.email || !form.password || !form.course_id} onClick={add}>
            Add user
          </Button>
          {error && (
            <div className="sm:col-span-2">
              <ErrorCard message={error} />
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>
            Teachers &amp; students{users ? ` (${users.length})` : ""}
          </CardTitle>
          <CardDescription>
            Search by name, email, role, or course. Results are shown 25 at a time.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {users === null ? (
            <SkeletonList />
          ) : users.length === 0 ? (
            <EmptyState
              icon={<Users />}
              title="No users yet"
              message="Add your first teacher or student using the form above."
            />
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <Input
                  type="search"
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setPage(1);
                  }}
                  placeholder="Search users"
                  aria-label="Search teachers and students"
                  className="sm:max-w-sm"
                />
                <p className="text-xs text-muted-foreground" aria-live="polite">
                  Showing {firstResult}–{lastResult} of {filteredUsers.length}
                </p>
              </div>

              {filteredUsers.length === 0 ? (
                <EmptyState
                  icon={<Users />}
                  title="No matching users"
                  message="Try a different name, email, role, or course."
                />
              ) : (
                <ul className="flex max-h-[38rem] flex-col divide-y overflow-y-auto pr-1">
                  {pageUsers.map((u) => {
                    const name = u.full_name || u.email || "";
                    return (
                      <li
                        key={u.id}
                        className="flex items-center justify-between gap-3 py-3 text-sm"
                      >
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                        {initials(name)}
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-semibold text-foreground">
                            {name}
                          </span>
                          <span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-xs font-medium">
                            {statusLabel(u.role)}
                          </span>
                        </div>
                        <div className="truncate text-xs text-muted-foreground">
                          {u.email}
                          {u.courses.length ? " · " + u.courses.join(", ") : ""}
                        </div>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {u.role === "teacher" && (
                        <button
                          type="button"
                          className="rounded-lg border border-input px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent"
                          onClick={() => openSubjectAssignments(u)}
                        >
                          Subjects
                        </button>
                      )}
                      <button
                        type="button"
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                        disabled={busy}
                        aria-label={`Remove ${name}`}
                        onClick={() => setConfirmDel(u)}
                      >
                        <Trash size={16} />
                      </button>
                    </div>
                      </li>
                    );
                  })}
                </ul>
              )}

              {filteredUsers.length > USERS_PER_PAGE && (
                <div className="flex items-center justify-between border-t pt-4">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={currentPage === 1}
                    onClick={() => setPage((value) => Math.max(1, value - 1))}
                  >
                    Previous
                  </Button>
                  <span className="text-sm text-muted-foreground">
                    Page {currentPage} of {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={currentPage === totalPages}
                    onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                  >
                    Next
                  </Button>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {manageTeacher && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget && !savingSubjects) {
              setManageTeacher(null);
            }
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="subject-assignment-title"
            className="animate-rise flex max-h-[85vh] w-full max-w-md flex-col rounded-2xl border border-border bg-card shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3 border-b p-5">
              <div>
                <h3 id="subject-assignment-title" className="text-base font-bold text-foreground">
                  Assign subjects
                </h3>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Choose the subjects that {manageTeacher.full_name || manageTeacher.email} can
                  access and manage.
                </p>
              </div>
              <button
                type="button"
                onClick={() => !savingSubjects && setManageTeacher(null)}
                aria-label="Close subject assignments"
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
                        <div className="flex flex-col gap-1">
                          {course.subjects.map((subject) => (
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
                disabled={savingSubjects || loadingSubjects || Boolean(assignmentError)}
              >
                {savingSubjects ? "Saving…" : "Save subjects"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {confirmDel && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={(e) => e.target === e.currentTarget && !busy && setConfirmDel(null)}
        >
          <div className="animate-rise w-full max-w-sm rounded-2xl border border-border bg-card p-6 shadow-2xl">
            <div className="mb-3 flex items-start justify-between gap-3">
              <h3 className="text-base font-bold text-foreground">Remove user</h3>
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
        </div>
      )}
    </div>
  );
}
