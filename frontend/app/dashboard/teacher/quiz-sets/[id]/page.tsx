"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { QuestionReviewCard } from "@/components/question-review-card";
import { QuizSetDetail, ReviewQuestion, getQuizSet, publishQuizSet } from "@/lib/api";

export default function ReviewPage({ params }: { params: { id: string } }) {
  const [detail, setDetail] = useState<QuizSetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    getQuizSet(params.id)
      .then(setDetail)
      .catch((e) => setError(e.message));
  }, [params.id]);

  // Replace one question in local state after an action, without a full refetch.
  function updateQuestion(updated: ReviewQuestion) {
    setDetail((d) =>
      d
        ? {
            ...d,
            variants: d.variants.map((v) => ({
              ...v,
              questions: v.questions.map((q) =>
                q.id === updated.id ? updated : q,
              ),
            })),
          }
        : d,
    );
  }

  async function handlePublish() {
    setError(null);
    setPublishing(true);
    try {
      const s = await publishQuizSet(params.id);
      setDetail((d) => (d ? { ...d, status: s.status } : d));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Publish failed");
    } finally {
      setPublishing(false);
    }
  }

  if (error) {
    return (
      <main className="mx-auto max-w-3xl p-8">
        <p className="text-red-600">{error}</p>
      </main>
    );
  }
  if (!detail) {
    return (
      <main className="mx-auto max-w-3xl p-8">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/dashboard/teacher" className="text-sm underline">
            ← Back to dashboard
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">{detail.title}</h1>
          <p className="text-sm text-muted-foreground">Status: {detail.status}</p>
        </div>
        <Button
          onClick={handlePublish}
          disabled={publishing || detail.status === "published"}
        >
          {detail.status === "published"
            ? "Published"
            : publishing
              ? "Publishing…"
              : "Publish"}
        </Button>
      </div>

      {detail.variants.map((v) => (
        <section key={v.id} className="flex flex-col gap-4">
          <h2 className="text-lg font-medium capitalize">
            {v.variant_type} variant
          </h2>
          {v.questions.map((q, i) => (
            <QuestionReviewCard
              key={q.id}
              index={i}
              question={q}
              onChange={updateQuestion}
            />
          ))}
        </section>
      ))}
    </main>
  );
}
