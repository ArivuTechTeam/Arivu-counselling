"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { BarChart3, BookOpen, Check, Plus, Users } from "@/components/ui/icons";

export function QuickActionsBar({
  courseCount,
  subjectCount,
  teacherCount,
}: {
  courseCount: number;
  subjectCount: number;
  teacherCount: number;
}) {
  const academicsReady = courseCount > 0 && subjectCount > 0;
  const steps = [
    { label: "Create a course", done: courseCount > 0 },
    { label: "Add a subject", done: subjectCount > 0 },
    { label: "Add a teacher", done: teacherCount > 0 },
  ];

  return (
    <section className="rounded-2xl border bg-card p-4 shadow-sm">
      {!academicsReady && (
        <div className="mb-4 rounded-xl border border-primary/20 bg-primary/[0.04] p-4">
          <p className="font-semibold text-foreground">Finish institution setup</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Teachers must be assigned to a subject, so create the course and subject first.
          </p>
          <ol className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
            {steps.map((step, index) => (
              <li key={step.label} className="flex items-center gap-2">
                <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${step.done ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>
                  {step.done ? <Check size={14} /> : index + 1}
                </span>
                <span className={step.done ? "text-muted-foreground line-through" : "font-medium"}>{step.label}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-2 text-xs font-bold uppercase tracking-widest text-muted-foreground">
          Quick actions
        </span>
        <Button asChild size="sm">
          <Link href={academicsReady ? "/dashboard/institution-admin/users#add-teacher" : "/dashboard/institution-admin/courses"}>
            {academicsReady ? <Users size={16} className="mr-2" /> : <BookOpen size={16} className="mr-2" />}
            {academicsReady ? "Add teacher" : "Create course & subject"}
          </Link>
        </Button>
        {academicsReady && (
          <Button asChild size="sm" variant="outline">
            <Link href="/dashboard/institution-admin/courses">
              <Plus size={16} className="mr-2" /> Manage courses
            </Link>
          </Button>
        )}
        <Button asChild size="sm" variant="outline">
          <Link href="/dashboard/institution-admin/analytics">
            <BarChart3 size={16} className="mr-2" /> View analytics
          </Link>
        </Button>
      </div>
    </section>
  );
}
