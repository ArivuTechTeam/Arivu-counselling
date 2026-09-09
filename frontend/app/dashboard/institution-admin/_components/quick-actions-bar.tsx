"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { BarChart3, Plus, Users } from "@/components/ui/icons";

export function QuickActionsBar() {
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
        <Button asChild size="sm" variant="outline">
          <Link href="/dashboard/institution-admin/analytics">
            <BarChart3 size={16} className="mr-2" /> View analytics
          </Link>
        </Button>
      </div>
    </section>
  );
}
