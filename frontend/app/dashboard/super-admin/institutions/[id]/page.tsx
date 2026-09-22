"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import {
  InstitutionOfferings,
  InstitutionRow,
  getInstitutionOfferings,
  getPlatformOverview,
} from "@/lib/api";

export default function InstitutionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [institution, setInstitution] = useState<
    InstitutionRow | null | undefined
  >();
  const [offerings, setOfferings] = useState<
    InstitutionOfferings | null | undefined
  >();
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    Promise.all([getPlatformOverview(), getInstitutionOfferings(id)])
      .then(([overview, offeringData]) => {
        setInstitution(
          overview.institutions_table.find((row) => row.id === id) ?? null,
        );
        setOfferings(offeringData);
      })
      .catch((reason) => {
        setInstitution(null);
        setOfferings(null);
        setError(reason.message);
      });
  }
  useEffect(load, [id]);

  const metrics = institution
    ? [
        ["Teachers", institution.teachers],
        ["Students", institution.students],
        ["Courses", institution.course_count],
        ["Levels", institution.level_count],
        ["Subjects", institution.subject_count],
        ["Quiz sets", institution.quiz_sets],
        ["Published", institution.published],
        ["Graded attempts", institution.attempts],
        ["Accuracy", `${institution.accuracy}%`],
        ["Admins", institution.admins],
        ["Status", institution.is_active ? "Active" : "Inactive"],
      ]
    : [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={institution?.name ?? "Institution details"}
        description="Tenant-scoped platform metrics for this institution."
      />
      <Link
        href="/dashboard/super-admin/institutions"
        className="w-fit text-sm font-semibold text-primary hover:underline"
      >
        ← Back to institutions
      </Link>
      {error ? (
        <ErrorCard message={error} onRetry={load} />
      ) : institution === undefined || offerings === undefined ? (
        <SkeletonList rows={4} />
      ) : institution === null || offerings === null ? (
        <EmptyState
          title="Institution not found"
          message="This institution may have been removed."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {metrics.map(([label, value]) => (
              <Card key={label}>
                <CardContent className="p-5">
                  <strong className="text-2xl">{value}</strong>
                  <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {label}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Academic offerings</CardTitle>
              <CardDescription>
                Courses, levels and subjects currently provisioned for this
                institution, including anything its admin added manually.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {offerings.courses.length === 0 ? (
                <EmptyState
                  title="No courses assigned"
                  message="Edit the institution's offerings or ask its administrator to add a course."
                />
              ) : (
                <div className="grid gap-4 lg:grid-cols-2">
                  {offerings.courses.map((course) => (
                    <section key={course.id} className="rounded-xl border bg-muted/20 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <h3 className="font-semibold text-foreground">{course.name}</h3>
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                          {course.levels.length} level{course.levels.length === 1 ? "" : "s"}
                        </span>
                      </div>
                      <div className="mt-4 flex flex-col gap-3">
                        {course.levels.map((level) => (
                          <div key={level.id} className="rounded-lg border bg-card p-3">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-sm font-semibold">{level.name}</p>
                              <span className="text-xs text-muted-foreground">
                                {level.subjects.length} subject{level.subjects.length === 1 ? "" : "s"}
                              </span>
                            </div>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {level.subjects.map((subject) => (
                                <span
                                  key={subject.id}
                                  className="rounded-full border bg-background px-2 py-1 text-xs text-muted-foreground"
                                >
                                  {subject.name}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Administration boundary</CardTitle>
              <CardDescription>
                Super administrators can monitor this tenant here. Managing
                teachers, courses, and quizzes requires signing in as one of
                this institution&apos;s administrators.
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              This separation prevents a platform account from silently
              entering a tenant administrator session.
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
