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
  Course,
  createCourse,
  createSubject,
  deleteCourse,
  deleteSubject,
  listCourses,
} from "@/lib/api";

export function CourseManager() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [newCourse, setNewCourse] = useState("");
  const [newSubject, setNewSubject] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function refresh() {
    listCourses()
      .then(setCourses)
      .catch((e) => setError(e.message));
  }
  useEffect(refresh, []);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Courses &amp; subjects</CardTitle>
          <CardDescription>
            Add the courses and subjects your institution offers. Students and
            teachers pick a course when they sign up.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex gap-2">
            <Input
              placeholder="New course (e.g. CA Foundation)"
              value={newCourse}
              onChange={(e) => setNewCourse(e.target.value)}
            />
            <Button
              disabled={busy || !newCourse.trim()}
              onClick={() =>
                run(async () => {
                  await createCourse(newCourse.trim());
                  setNewCourse("");
                })
              }
            >
              Add course
            </Button>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </CardContent>
      </Card>

      {courses.length === 0 ? (
        <p className="text-sm text-muted-foreground">No courses yet.</p>
      ) : (
        courses.map((c) => (
          <Card key={c.id}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>{c.name}</CardTitle>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => run(() => deleteCourse(c.id))}
                >
                  Delete course
                </Button>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {c.subjects.length === 0 ? (
                <p className="text-sm text-muted-foreground">No subjects yet.</p>
              ) : (
                <ul className="flex flex-col divide-y">
                  {c.subjects.map((s) => (
                    <li
                      key={s.id}
                      className="flex items-center justify-between py-2 text-sm"
                    >
                      {s.name}
                      <button
                        className="text-xs text-red-600 hover:underline"
                        disabled={busy}
                        onClick={() => run(() => deleteSubject(s.id))}
                      >
                        remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex gap-2">
                <Input
                  placeholder="New subject (e.g. Accounting)"
                  value={newSubject[c.id] ?? ""}
                  onChange={(e) =>
                    setNewSubject((m) => ({ ...m, [c.id]: e.target.value }))
                  }
                />
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy || !(newSubject[c.id] ?? "").trim()}
                  onClick={() =>
                    run(async () => {
                      await createSubject(c.id, (newSubject[c.id] ?? "").trim());
                      setNewSubject((m) => ({ ...m, [c.id]: "" }));
                    })
                  }
                >
                  Add subject
                </Button>
              </div>
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}
