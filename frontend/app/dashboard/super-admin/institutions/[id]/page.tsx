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
import { InstitutionRow, getPlatformOverview } from "@/lib/api";

export default function InstitutionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [institution, setInstitution] = useState<
    InstitutionRow | null | undefined
  >();
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    getPlatformOverview()
      .then((overview) =>
        setInstitution(
          overview.institutions_table.find((row) => row.id === id) ?? null,
        ),
      )
      .catch((reason) => setError(reason.message));
  }
  useEffect(load, [id]);

  const metrics = institution
    ? [
        ["Teachers", institution.teachers],
        ["Students", institution.students],
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
      ) : institution === undefined ? (
        <SkeletonList rows={4} />
      ) : institution === null ? (
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
