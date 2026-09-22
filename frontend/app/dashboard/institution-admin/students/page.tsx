"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { Users } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import { listCourseStudents } from "@/lib/api";
import { useCourses } from "@/lib/staff-queries";

const EMPTY_COURSES: NonNullable<ReturnType<typeof useCourses>["data"]> = [];

export default function InstitutionStudentsPage() {
  const coursesQuery = useCourses();
  const courses = coursesQuery.data ?? EMPTY_COURSES;
  const [courseId, setCourseId] = useState("");

  useEffect(() => {
    if (!courseId && courses.length > 0) setCourseId(courses[0].id);
  }, [courseId, courses]);

  const rosterQuery = useSWR(
    courseId ? ["staff:institution:course-roster", courseId] : null,
    () => listCourseStudents(courseId),
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Students"
        description="View enrolled students directly by course. Teacher assignments remain under Teachers."
      />

      {coursesQuery.error ? (
        <ErrorCard
          message={coursesQuery.error.message}
          onRetry={() => void coursesQuery.mutate()}
        />
      ) : coursesQuery.data !== undefined && courses.length === 0 ? (
        <EmptyState
          icon={<Users size={24} />}
          title="No courses yet"
          message="Create a course before students can be enrolled and shown here."
          action={
            <Button asChild size="sm">
              <Link href="/dashboard/institution-admin/courses">
                Create a course
              </Link>
            </Button>
          }
        />
      ) : (
        <Card>
          <CardHeader className="gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>Course roster</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Choose a course to see its enrolled students.
              </p>
            </div>
            <label className="flex min-w-56 flex-col gap-1 text-xs font-semibold text-muted-foreground">
              Course
              <select
                value={courseId}
                onChange={(event) => setCourseId(event.target.value)}
                disabled={coursesQuery.data === undefined}
                className="h-10 rounded-md border border-input bg-background px-3 text-sm font-normal text-foreground outline-none focus:ring-2 focus:ring-ring"
              >
                {coursesQuery.data === undefined && <option>Loading courses…</option>}
                {courses.map((course) => (
                  <option key={course.id} value={course.id}>
                    {course.name}
                  </option>
                ))}
              </select>
            </label>
          </CardHeader>
          <CardContent>
            {!courseId || rosterQuery.data === undefined ? (
              <SkeletonList rows={5} />
            ) : rosterQuery.error ? (
              <ErrorCard
                message={rosterQuery.error.message}
                onRetry={() => void rosterQuery.mutate()}
              />
            ) : rosterQuery.data.students.length === 0 ? (
              <EmptyState
                icon={<Users size={24} />}
                title="No students enrolled"
                message="Students enrolled in this course will appear here."
              />
            ) : (
              <div className="overflow-x-auto rounded-xl border">
                <table className="w-full min-w-[560px] text-sm">
                  <thead className="bg-secondary/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="px-4 py-3">Student</th>
                      <th className="px-4 py-3">Email</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {rosterQuery.data.students.map((student) => (
                      <tr key={student.id}>
                        <td className="px-4 py-3 font-medium text-foreground">
                          {student.full_name || "Unnamed student"}
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">
                          {student.email || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
