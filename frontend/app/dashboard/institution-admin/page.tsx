"use client";

import { useEffect, useState } from "react";

import { StatCard } from "@/components/stat-card";
import { AdminStats, getAdminStats } from "@/lib/api";

export default function InstitutionOverview() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAdminStats()
      .then(setStats)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!stats) return <p className="text-muted-foreground">Loading…</p>;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <StatCard label="Teachers" value={stats.teachers} />
        <StatCard label="Students" value={stats.students} />
        <StatCard label="Courses" value={stats.courses} />
        <StatCard label="Subjects" value={stats.subjects} />
        <StatCard label="Quiz sets" value={stats.quiz_sets} />
        <StatCard label="Published" value={stats.published_quizzes} />
      </div>
    </div>
  );
}
