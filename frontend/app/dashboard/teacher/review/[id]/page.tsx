"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton, SkeletonCards } from "@/components/ui/skeleton";
import { SparkBurst } from "@/components/ui/spark-burst";
import { useToast } from "@/components/ui/toast";
import { QuestionPaperButtons } from "@/components/shared/pdf-buttons";
import { QuestionReviewCard } from "@/components/teacher/question-review-card";
import { QuestionReviewNavigator } from "@/components/teacher/question-review-navigator";
import { statusLabel, variantLabel } from "@/lib/format";
import {
  QuizSetDetail,
  ReviewQuestion,
  archiveQuizSet,
  approveAllQuestions,
  getQuizSet,
  publishQuizSet,
} from "@/lib/api";

type ReviewFilter =
  | "all"
  | "pending_review"
  | "approved"
  | "rejected"
  | "needs_edit";

function StatusFilter({
  label,
  value,
  color,
  active,
  onClick,
}: {
  label: string;
  value: number;
  color: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex min-w-[92px] items-center gap-3 rounded-xl border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
        active
          ? "border-primary/35 bg-primary/10 shadow-sm"
          : "border-transparent bg-muted/45 hover:border-input hover:bg-muted"
      }`}
    >
      <span className={`text-2xl font-bold leading-none tracking-tight ${color}`}>
        {value}
      </span>
      <div className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
        {label}
      </div>
    </button>
  );
}

export default function ReviewDetailPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const { notify } = useToast();
  const [detail, setDetail] = useState<QuizSetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [approving, setApproving] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [activeQuestionId, setActiveQuestionId] = useState<string | null>(null);
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  // One-shot spark burst on the big "win" actions (publish / approve-all).
  const [celebrate, setCelebrate] = useState(false);

  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(
        `teacher-review-filter:${params.id}`,
      );
      if (
        saved === "all" ||
        saved === "pending_review" ||
        saved === "approved" ||
        saved === "rejected" ||
        saved === "needs_edit"
      ) {
        setReviewFilter(saved);
      }
    } catch {
      // Filtering remains usable without session storage.
    }
  }, [params.id]);

  function celebrateBurst() {
    setCelebrate(true);
    window.setTimeout(() => setCelebrate(false), 900);
  }

  function load() {
    setError(null);
    getQuizSet(params.id)
      .then(setDetail)
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setDetail(null);
    getQuizSet(params.id)
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason.message);
      });
    return () => {
      cancelled = true;
    };
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

  function navigateToQuestion(questionId: string) {
    setActiveQuestionId(questionId);
    document
      .getElementById(`review-question-${questionId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function handlePublish() {
    setError(null);
    setPublishing(true);
    try {
      const s = await publishQuizSet(params.id);
      setDetail((d) => (d ? { ...d, status: s.status } : d));
      celebrateBurst();
      notify("🎉 Quiz published — students can now see it", "success");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Publish failed");
    } finally {
      setPublishing(false);
    }
  }

  async function handleApproveAll() {
    setError(null);
    setApproving(true);
    const count = detail
      ? detail.variants
          .flatMap((v) => v.questions)
          .filter(
            (q) =>
              q.review_status === "pending_review" &&
              q.verification_status !== "unsupported",
          ).length
      : 0;
    try {
      await approveAllQuestions(params.id);
      setDetail(await getQuizSet(params.id));
      celebrateBurst();
      notify(
        count > 0
          ? `✓ ${count} question${count === 1 ? "" : "s"} approved`
          : "✓ All questions approved",
        "success",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve all failed");
    } finally {
      setApproving(false);
    }
  }

  async function handleArchive() {
    const warning = detail?.status === "published"
      ? "Archive this quiz? Students will no longer see it, but attempts and analytics will be kept."
      : "Archive this quiz? Its questions and history will be kept.";
    if (!window.confirm(warning)) return;
    setArchiving(true);
    setError(null);
    try {
      await archiveQuizSet(params.id);
      notify("Quiz archived", "success");
      router.push("/dashboard/teacher/review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Archive failed");
      setArchiving(false);
    }
  }

  if (error && !detail)
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-6">
        <ErrorCard message={error} onRetry={load} />
      </div>
    );
  if (!detail)
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-6">
        <Skeleton className="h-5 w-40 rounded-md" />
        <Skeleton className="h-24 w-full rounded-2xl" />
        <SkeletonCards count={3} />
      </div>
    );

  const all = detail.variants.flatMap((v) => v.questions);
  const pending = all.filter((q) => q.review_status === "pending_review").length;
  const approved = all.filter((q) => q.review_status === "approved").length;
  const rejected = all.filter((q) => q.review_status === "rejected").length;
  const needsEdit = all.filter((q) => q.review_status === "needs_edit").length;
  const unresolved = pending + needsEdit;
  const approvablePending = all.filter(
    (q) =>
      q.review_status === "pending_review" &&
      q.verification_status !== "unsupported",
  ).length;
  const questionNumbers = Object.fromEntries(
    all.map((question, index) => [question.id, index + 1]),
  );
  const visibleVariants = detail.variants
    .map((variant) => ({
      ...variant,
      questions:
        reviewFilter === "all"
          ? variant.questions
          : variant.questions.filter(
              (question) => question.review_status === reviewFilter,
            ),
    }))
    .filter((variant) => variant.questions.length > 0);
  const visibleQuestions = visibleVariants.flatMap((variant) => variant.questions);
  const visibleActiveQuestionId = visibleQuestions.some(
    (question) => question.id === activeQuestionId,
  )
    ? activeQuestionId
    : (visibleQuestions[0]?.id ?? null);

  function chooseFilter(filter: ReviewFilter) {
    setReviewFilter(filter);
    try {
      window.sessionStorage.setItem(`teacher-review-filter:${params.id}`, filter);
    } catch {
      // Filtering remains usable without session storage.
    }
    const first = all.find(
      (question) => filter === "all" || question.review_status === filter,
    );
    setActiveQuestionId(first?.id ?? null);
    window.requestAnimationFrame(() => {
      document
        .getElementById("review-question-list")
        ?.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  return (
    <div className="mx-auto flex h-full max-w-7xl flex-col gap-4">
      <div className="sticky top-0 z-[9] -mx-1 bg-background/95 px-1 pb-3 backdrop-blur supports-[backdrop-filter]:bg-background/85">
        <div className="animate-rise relative overflow-hidden rounded-2xl border bg-card shadow-sm">
          {celebrate && <SparkBurst count={24} />}

          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-5">
            <div className="min-w-0">
              <Link
                href="/dashboard/teacher/review"
                className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                ← Review queue
              </Link>
              <div className="mt-1 flex min-w-0 items-center gap-2">
                <h1 className="truncate text-xl font-semibold tracking-tight">
                  {detail.title}
                </h1>
                <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                  {statusLabel(detail.status)}
                </span>
              </div>
            </div>
            <QuestionPaperButtons
              quizSetId={params.id}
              title={detail.title}
              compact
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-5">
            <div className="flex max-w-full gap-2 overflow-x-auto pb-0.5" aria-label="Filter questions by review status">
              <StatusFilter
                label="All"
                value={all.length}
                color="text-foreground"
                active={reviewFilter === "all"}
                onClick={() => chooseFilter("all")}
              />
              <StatusFilter
                label="Pending"
                value={pending}
                color="text-amber-600"
                active={reviewFilter === "pending_review"}
                onClick={() => chooseFilter("pending_review")}
              />
              <StatusFilter
                label="Needs edit"
                value={needsEdit}
                color="text-orange-600"
                active={reviewFilter === "needs_edit"}
                onClick={() => chooseFilter("needs_edit")}
              />
              <StatusFilter
                label="Approved"
                value={approved}
                color="text-emerald-600"
                active={reviewFilter === "approved"}
                onClick={() => chooseFilter("approved")}
              />
              <StatusFilter
                label="Rejected"
                value={rejected}
                color="text-rose-500"
                active={reviewFilter === "rejected"}
                onClick={() => chooseFilter("rejected")}
              />
            </div>

          <div className="flex shrink-0 items-center gap-2">
          {detail.status === "published" && (
            <Link href={`/dashboard/teacher/performance/${params.id}`}>
              <Button size="sm" variant="outline">View performance</Button>
            </Link>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={handleArchive}
            disabled={archiving || publishing || approving}
          >
            {archiving
              ? "Archiving…"
              : detail.status === "published"
                ? "Unpublish & archive"
                : "Archive"}
          </Button>
          {approvablePending > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleApproveAll}
              disabled={approving || publishing}
            >
              {approving ? "Approving…" : `Approve all (${approvablePending})`}
            </Button>
          )}
          <Button
            size="sm"
            onClick={handlePublish}
            disabled={publishing || detail.status === "published" || unresolved > 0}
            title={
              unresolved > 0
                ? `Review ${unresolved} remaining question${unresolved === 1 ? "" : "s"} before publishing`
                : undefined
            }
          >
            {detail.status === "published"
              ? "Published"
              : publishing
                ? "Publishing…"
                : "Publish"}
          </Button>
            </div>
          </div>
        </div>
      </div>

      {error && (
        <p className="text-sm text-destructive">{error}</p>
      )}
      {detail.status !== "published" && unresolved > 0 && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Review {unresolved} remaining question{unresolved === 1 ? "" : "s"} before
          publishing. Questions marked “Needs edit” must be edited or regenerated.
        </p>
      )}

      <div className="grid min-h-0 flex-1 items-start gap-4 lg:grid-cols-[210px_minmax(0,1fr)]">
        <QuestionReviewNavigator
          variants={visibleVariants}
          questionNumbers={questionNumbers}
          totalQuestions={all.length}
          activeQuestionId={visibleActiveQuestionId}
          onNavigate={navigateToQuestion}
        />

        <div
          id="review-question-list"
          className="min-w-0 space-y-6 lg:max-h-[calc(100vh-15.5rem)] lg:overflow-y-auto lg:pr-2"
        >
          {visibleVariants.map((v) => (
            <section key={v.id} className="flex flex-col gap-4">
              <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                {variantLabel(v.variant_type)} version
              </h2>
              {v.questions.map((q) => {
                const globalIndex = all.findIndex((question) => question.id === q.id);
                return (
                  <div
                    key={q.id}
                    id={`review-question-${q.id}`}
                    className="scroll-mt-3"
                  >
                    <QuestionReviewCard
                      index={globalIndex}
                      question={q}
                      onChange={updateQuestion}
                    />
                  </div>
                );
              })}
            </section>
          ))}
          {visibleQuestions.length === 0 && (
            <div className="flex min-h-64 flex-col items-center justify-center rounded-2xl border border-dashed bg-card/60 px-6 text-center">
              <p className="font-semibold">No questions in this view</p>
              <p className="mt-1 text-sm text-muted-foreground">
                The count updates immediately as questions move between review states.
              </p>
              <Button
                className="mt-4"
                size="sm"
                variant="outline"
                onClick={() => chooseFilter("all")}
              >
                Show all questions
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
