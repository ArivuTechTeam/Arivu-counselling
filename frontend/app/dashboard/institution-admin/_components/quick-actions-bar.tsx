"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { AlertTriangle, BarChart3, BookOpen, Plus, Users } from "@/components/ui/icons";

export function QuickActionsBar({
  pendingReviewCount,
  onPending,
  onFindings,
}: {
  pendingReviewCount: number;
  onPending: () => void;
  onFindings: () => void;
}) {
  return (
    <section className="rounded-2xl border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-2 text-xs font-bold uppercase tracking-widest text-muted-foreground">
          Quick actions
        </span>
        <Button asChild size="sm">
          <Link href="/dashboard/institution-admin/users">
            <Users size={16} className="mr-2" /> Add teacher
          </Link>
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link href="/dashboard/institution-admin/courses">
            <Plus size={16} className="mr-2" /> Add course
          </Link>
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onPending}>
          <BookOpen size={16} className="mr-2" /> Review pending
          {pendingReviewCount > 0 && (
            <span className="ml-2 rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-bold text-rose-700">
              {pendingReviewCount}
            </span>
          )}
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link href="/dashboard/institution-admin/analytics">
            <BarChart3 size={16} className="mr-2" /> View analytics
          </Link>
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onFindings}>
          <AlertTriangle size={16} className="mr-2" /> View findings
        </Button>
      </div>
    </section>
  );
}
