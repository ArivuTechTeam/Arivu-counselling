"use client";

import { useEffect, useState } from "react";

import { StatCard } from "@/components/stat-card";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PlatformStats, getPlatformStats } from "@/lib/api";

export default function PlatformOverview() {
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPlatformStats()
      .then(setStats)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!stats) return <p className="text-muted-foreground">Loading…</p>;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Institutions" value={stats.institutions} />
        <StatCard label="Total teachers" value={stats.total_teachers} />
        <StatCard label="Total students" value={stats.total_students} />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Institutions</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-col divide-y">
            {stats.per_institution.map((i) => (
              <li key={i.id} className="flex items-center justify-between py-3 text-sm">
                <span className="font-medium">{i.name}</span>
                <span className="text-muted-foreground">
                  {i.teachers} teachers · {i.students} students
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
