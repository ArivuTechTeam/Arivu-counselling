"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { QuestionPaperButtons } from "@/components/pdf-buttons";
import { QuestionReviewCard } from "@/components/question-review-card";
import {
  QuizSetDetail,
  ReviewQuestion,
  approveAllQuestions,
  getQuizSet,
  publishQuizSet,
} from "@/lib/api";

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
        {label}
      </div>
      <div className={`mt-1 text-3xl font-bold tracking-tight ${color}`}>{value}</div>
    </div>
  );
}

export default function ReviewDetailPage({ params }: { params: { id: string } }) {
  const [detail, setDetail] = useState<QuizSetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [approving, setApproving] = useState(false);

  useEffect(() => {
    getQuizSet(params.id)
      .then(setDetail)
      .catch((e) => setError(e.message));
  }, [params.id]);

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

  async function handleApproveAll() {
    setError(null);
    setApproving(true);
    try {
      await approveAllQuestions(params.id);
      setDetail(await getQuizSet(params.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve all failed");
    } finally {
      setApproving(false);
    }
  }

  if (error) return <p className="text-red-600">{error}</p>;
  if (!detail) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const all = detail.variants.flatMap((v) => v.questions);
  const pending = all.filter((q) => q.review_status === "pending_review").length;
  const approved = all.filter((q) => q.review_status === "approved").length;
  const rejected = all.filter((q) => q.review_status === "rejected").length;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <Link
        href="/dashboard/teacher/review"
        className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        ← Back to review queue
      </Link>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{detail.title}</h1>
          <p className="mt-1 text-sm capitalize text-muted-foreground">
            Status: {detail.status}
          </p>
        </div>
        <QuestionPaperButtons quizSetId={params.id} title={detail.title} />
      </div>

      {/* Stat header (screenshot-2 style) */}
      <div className="animate-rise flex flex-wrap items-center justify-between gap-4 rounded-2xl border bg-card p-5 shadow-sm">
        <div className="flex flex-wrap items-center gap-8">
          <Stat label="Pending" value={pending} color="text-amber-600" />
          <Stat label="Approved" value={approved} color="text-emerald-600" />
          <Stat label="Rejected" value={rejected} color="text-rose-500" />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {pending > 0 && (
            <Button
              variant="outline"
              onClick={handleApproveAll}
              disabled={approving || publishing}
            >
              {approving ? "Approving…" : `Approve all (${pending})`}
            </Button>
          )}
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
      </div>

      {detail.variants.map((v) => (
        <section key={v.id} className="flex flex-col gap-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
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
    </div>
  );
}
