"use client";

import { useEffect, useState } from "react";

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
import { SkeletonList } from "@/components/ui/skeleton";
import { statusLabel } from "@/lib/format";
import {
  AdminUser,
  Course,
  createUser,
  deleteUser,
  listCourses,
  listUsers,
} from "@/lib/api";

const selectClass =
  "h-9 rounded-md border border-input bg-transparent px-3 text-sm";

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

  function refresh() {
    listUsers().then(setUsers).catch((e) => setError(e.message));
  }
  useEffect(() => {
    refresh();
    listCourses().then(setCourses).catch(() => {});
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
        course_id: form.course_id || undefined,
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

  return (
    <div className="flex flex-col gap-6">
      <Card>
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
            <option value="">No course</option>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <Button disabled={busy || !form.full_name || !form.email || !form.password} onClick={add}>
            Add user
          </Button>
          {error && (
            <div className="sm:col-span-2">
              <ErrorCard message={error} />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            Teachers &amp; students{users ? ` (${users.length})` : ""}
          </CardTitle>
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
            <ul className="flex flex-col divide-y">
              {users.map((u) => {
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
                    <button
                      className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                      disabled={busy}
                      aria-label={`Remove ${name}`}
                      onClick={() => setConfirmDel(u)}
                    >
                      <Trash size={16} />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

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
