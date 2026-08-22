"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { QuizSetSummary, listQuizSets } from "@/lib/api";

const SET_TONE: Record<string, string> = {
  published: "bg-emerald-100 text-emerald-700",
  draft: "bg-muted text-muted-foreground",
  archived: "bg-muted text-muted-foreground",
};

export function QuizSetList() {
  const [sets, setSets] = useState<QuizSetSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listQuizSets()
      .then(setSets)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your quizzes</CardTitle>
        <CardDescription>Review and publish generated quiz sets.</CardDescription>
      </CardHeader>
      <CardContent>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {sets.length === 0 ? (
          <p className="text-sm text-muted-foreground">No quiz sets yet.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {sets.map((s) => (
              <Link
                key={s.id}
                href={`/dashboard/teacher/review/${s.id}`}
                className="flex items-center justify-between gap-4 rounded-lg border bg-card p-4 text-sm shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">{s.title}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Created {new Date(s.created_at).toLocaleDateString()}
                  </p>
                </div>
                <span className="flex shrink-0 items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      SET_TONE[s.status] ?? "bg-muted text-muted-foreground"
                    }`}
                  >
                    {s.status}
                  </span>
                  <span className="text-muted-foreground">→</span>
                </span>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
