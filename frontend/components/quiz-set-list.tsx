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
          <ul className="flex flex-col divide-y">
            {sets.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between gap-4 py-3 text-sm"
              >
                <Link
                  href={`/dashboard/teacher/quiz-sets/${s.id}`}
                  className="truncate underline"
                >
                  {s.title}
                </Link>
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs">
                  {s.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
