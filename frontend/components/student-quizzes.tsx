"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StudentQuiz, listStudentQuizzes, startAttempt } from "@/lib/api";

export function StudentQuizzes() {
  const router = useRouter();
  const [quizzes, setQuizzes] = useState<StudentQuiz[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);

  useEffect(() => {
    listStudentQuizzes()
      .then(setQuizzes)
      .catch((e) => setError(e.message));
  }, []);

  async function start(variantId: string) {
    setStarting(variantId);
    setError(null);
    try {
      const { attempt_id } = await startAttempt(variantId);
      router.push(`/dashboard/student/attempt/${attempt_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start quiz");
      setStarting(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Available quizzes</CardTitle>
        <CardDescription>Pick a variant to practise.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error && <p className="text-sm text-red-600">{error}</p>}
        {quizzes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No quizzes available yet.
          </p>
        ) : (
          quizzes.map((qz) => (
            <div key={qz.id} className="rounded-md border p-4">
              <p className="font-medium">{qz.title}</p>
              <div className="mt-2 flex flex-col gap-2">
                {qz.variants.map((v) => (
                  <div
                    key={v.id}
                    className="flex items-center justify-between gap-4 text-sm"
                  >
                    <span className="capitalize text-muted-foreground">
                      {v.variant_type} · {v.question_count} questions
                    </span>
                    <Button
                      size="sm"
                      onClick={() => start(v.id)}
                      disabled={starting === v.id}
                    >
                      {starting === v.id ? "Starting…" : "Start"}
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
