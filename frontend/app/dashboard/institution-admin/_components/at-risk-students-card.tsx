"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { InstitutionAnalytics } from "@/lib/api";

type Student = InstitutionAnalytics["at_risk_students"][number];

export function AtRiskStudentsCard({
  students,
  onSelect,
  onViewAll,
}: {
  students: Student[];
  onSelect: (student: Student) => void;
  onViewAll: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Students needing help</CardTitle>
        <CardDescription>Lowest accuracy first, with their weakest quiz.</CardDescription>
      </CardHeader>
      <CardContent>
        {students.length === 0 ? (
          <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
            No students are currently below the 40% threshold.
          </div>
        ) : (
          <div className="space-y-2">
            {students.slice(0, 5).map((student) => (
              <button
                key={student.student_id}
                type="button"
                onClick={() => onSelect(student)}
                className="grid w-full grid-cols-[1fr_auto] gap-3 rounded-xl border p-3 text-left transition hover:border-primary/35 hover:bg-accent"
              >
                <span className="min-w-0">
                  <strong className="block truncate text-sm">{student.name}</strong>
                  <span className="block truncate text-xs text-muted-foreground">
                    Weakest: {student.worst_quiz?.title ?? "No quiz details"}
                    {student.worst_quiz ? ` · ${student.worst_quiz.accuracy}%` : ""}
                  </span>
                  <span className="mt-1 block text-[11px] text-muted-foreground">
                    {student.attempts} attempt{student.attempts === 1 ? "" : "s"}
                  </span>
                </span>
                <strong className="text-sm text-rose-600">{student.accuracy}% →</strong>
              </button>
            ))}
            <button
              type="button"
              onClick={onViewAll}
              className="pt-2 text-sm font-semibold text-primary hover:underline"
            >
              View all {students.length} at-risk student{students.length === 1 ? "" : "s"} →
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
