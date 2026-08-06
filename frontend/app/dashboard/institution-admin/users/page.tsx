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
import { Input } from "@/components/ui/input";
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

export default function UsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
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
          <Input placeholder="Temporary password" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
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
          {error && <p className="text-sm text-red-600 sm:col-span-2">{error}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Teachers &amp; students ({users.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {users.length === 0 ? (
            <p className="text-sm text-muted-foreground">No users yet.</p>
          ) : (
            <ul className="flex flex-col divide-y">
              {users.map((u) => (
                <li key={u.id} className="flex items-center justify-between gap-3 py-3 text-sm">
                  <div>
                    <span className="font-medium">{u.full_name ?? "(no name)"}</span>{" "}
                    <span className="rounded-full bg-secondary px-2 py-0.5 text-xs capitalize">{u.role}</span>
                    <div className="text-xs text-muted-foreground">
                      {u.email}
                      {u.courses.length ? " · " + u.courses.join(", ") : ""}
                    </div>
                  </div>
                  <button className="text-xs text-red-600 hover:underline" disabled={busy} onClick={() => remove(u.id)}>
                    remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
