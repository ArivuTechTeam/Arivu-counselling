"use client";

import { useEffect, useRef, useState } from "react";
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
import { useDashboardIdentity } from "@/components/shared/dashboard-identity-context";
import { statusLabel, variantLabel } from "@/lib/format";
import {
  DocumentFigure,
  QuizSetDetail,
  ReviewQuestion,
  ScoringPolicy,
  archiveQuizSet,
  approveAllQuestions,
  getQuizSet,
  listDocumentFigures,
  publishQuizSet,
  duplicateQuizSet,
  listScoringPolicies,
  setQuizScoringPolicy,
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
  const { features } = useDashboardIdentity();
  const { notify } = useToast();
  const [detail, setDetail] = useState<QuizSetDetail | null>(null);
  const [documentFigures, setDocumentFigures] = useState<DocumentFigure[]>([]);
  const [error, setError] = useState<string | null>(null);
  const copyKey = useRef<string | null>(null);
  const [copying, setCopying] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [approving, setApproving] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [activeQuestionId, setActiveQuestionId] = useState<string | null>(null);
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [scoringPolicies, setScoringPolicies] = useState<ScoringPolicy[]>([]);
  const [savingPolicy, setSavingPolicy] = useState(false);
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

  useEffect(() => {
    if (!features.scoring_policies) return;
    listScoringPolicies().then(setScoringPolicies).catch(() => setScoringPolicies([]));
  }, [features.scoring_policies]);

  async function changeScoringPolicy(policyId: string) {
    if (!detail) return;
    setSavingPolicy(true);
    setError(null);
    try {
      const result = await setQuizScoringPolicy(params.id, policyId || null);
      setDetail({ ...detail, scoring_policy_id: result.scoring_policy_id });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Couldn't update scoring.");
    } finally {
      setSavingPolicy(false);
    }
  }

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

  // Load the source document's figure catalog once, so each card can show its
  // attached figure and offer swap/add. Empty (or absent document) is fine.
  useEffect(() => {
    const documentId = detail?.document_id;
    if (!documentId) {
      setDocumentFigures([]);
      return;
    }
    let cancelled = false;
    listDocumentFigures(documentId)
      .then((figures) => {
        if (!cancelled) setDocumentFigures(figures);
      })
      .catch(() => {
        if (!cancelled) setDocumentFigures([]);
      });
    return () => {
      cancelled = true;
    };
  }, [detail?.document_id]);

  function updateQuestion(updated: ReviewQuestion) {
    if (detail?.reuse_enabled) { load(); return; }
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

  async function handleDuplicate() {
    if (!detail || copying) return;
    setCopying(true);
    setError(null);
    const storageKey = `quiz-copy-intent:${params.id}`;
    try { copyKey.current = window.sessionStorage.getItem(storageKey); } catch { /* retry still retains the in-memory key */ }
    copyKey.current ??= crypto.randomUUID();
    try { window.sessionStorage.setItem(storageKey, copyKey.current); } catch { /* storage may be unavailable */ }
    try {
      const copied = await duplicateQuizSet(params.id, `Copy of ${detail.title}`.slice(0, 200), copyKey.current);
      try { window.sessionStorage.removeItem(storageKey); } catch { /* copy already saved */ }
      copyKey.current = null;
      router.push(`/dashboard/teacher/review/${copied.quiz_set_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not duplicate the quiz. Retry to recover the same draft.");
    } finally { setCopying(false); }
  }

  async function handlePublish() {
    setError(null);
    setPublishing(true);
    try {
      const s = await publishQuizSet(params.id, detail?.publication_token);
      setDetail((d) => d ? {
        ...d, status: s.status,
        release_locked: d.reuse_enabled ? true : d.release_locked,
        variants: d.reuse_enabled ? d.variants.map((v) => ({
          ...v, questions: v.questions.map((q) => ({ ...q, release_locked: true })),
        })) : d.variants,
      } : d);
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
    try {
      const { approved: count, skipped = 0 } = await approveAllQuestions(params.id);
      if (skipped) setError(`${skipped} question(s) need an answer-format correction or changed during approval. Open them to check.`);
      setDetail(await getQuizSet(params.id));
      celebrateBurst();
      notify(
        count > 0
          ? `✓ ${count} question${count === 1 ? "" : "s"} approved`
          : "No questions were ready for bulk approval. Open any with an invalid answer format to fix them.",
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
      q.review_status === "pending_review" || q.review_status === "needs_edit",
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
            {detail.reuse_enabled && <Button variant="outline" disabled={copying} onClick={handleDuplicate}>
              {copying ? "Copying..." : "Duplicate as draft"}
            </Button>}
            <QuestionPaperButtons
              quizSetId={params.id}
              title={detail.title}
              compact
            />
          </div>

          {detail.release_locked && <p className="px-5 py-3 text-sm text-muted-foreground">This paper is protected to preserve student results. Duplicate it to edit a new draft.</p>}
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
          {features.scoring_policies && detail.status === "draft" && (
            <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              Scoring
              <select
                className="h-9 max-w-52 rounded-md border border-input bg-background px-2 text-sm text-foreground"
                value={detail.scoring_policy_id ?? ""}
                disabled={savingPolicy}
                onChange={(event) => void changeScoringPolicy(event.target.value)}
              >
                <option value="">Standard — no deduction</option>
                {scoringPolicies.map((policy) => (
                  <option key={policy.id} value={policy.id}>{policy.name}</option>
                ))}
              </select>
            </label>
          )}
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
              disabled={approving || publishing || detail.release_locked}
            >
              {approving ? "Approving…" : `Approve all (${approvablePending})`}
            </Button>
          )}
          <Button
            size="sm"
            onClick={handlePublish}
            disabled={publishing || copying || detail.status === "published" || detail.status === "archived" || unresolved > 0}
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
      {detail.import_summaries?.map((summary) => (
        <details key={summary.extraction_job_id} open={summary.skipped > 0 || !!summary.source_inventory?.missing.length}
          className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <summary className="cursor-pointer font-medium">
            Import receipt: {summary.imported} imported, {summary.skipped} skipped
            from {" "}{summary.candidates} AI-detected candidates
          </summary>
          <p className="mt-2">
            Compare with your original paper: these counts do not prove every source question
            was detected. Candidate numbers below are extraction order, not original paper numbers.
          </p>
          {summary.issues.map((issue) => (
            <p key={issue.candidate_index} className="mt-2">
              Candidate {issue.candidate_index}: {issue.question_preview || "Unreadable question"}
              {" — "}{issue.reason}
            </p>
          ))}
          {summary.source_inventory && (
            <div className="mt-3 space-y-2">
              <p>Source check: {summary.source_inventory.detected} numbered questions detected;
                {" "}{summary.source_inventory.matched} matched to AI candidates. {summary.source_inventory.scope}</p>
              {summary.source_inventory.missing.map((item) => (
                <p key={item.source_id}>Not matched — source question {item.source_number}: {item.question_preview}</p>
              ))}
              {summary.source_inventory.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
              {summary.source_inventory.duplicate_matches.length > 0 && <p>Some source items matched multiple candidates. Check for repeated imports.</p>}
              <details>
                <summary className="cursor-pointer">Source question and answer tracking</summary>
                {summary.source_inventory.items.map((item) => (
                  <p key={`${item.source_id}-${item.candidate_index}`}>
                    Source {item.source_number} → candidate {item.candidate_index}: {item.state};
                    {" "}{item.answer_origin.replaceAll("_", " ")}
                  </p>
                ))}
              </details>
            </div>
          )}
          {summary.source_manifest && <p className="mt-2">
            {summary.source_manifest.pages.length} source pages; read using {summary.source_manifest.route === "vision" ? "visual document processing" : "document text"}.
            {summary.source_manifest.sparse_pages.length > 0 &&
              (summary.source_manifest.route === "vision"
                ? ` Pages with little readable text: ${summary.source_manifest.sparse_pages.join(", ")}. These were included in visual processing.`
                : ` Pages with little readable text: ${summary.source_manifest.sparse_pages.join(", ")}. Image-only details are not interpreted in the current text workflow.`)}
          </p>}
        </details>
      ))}
      {detail.status !== "published" && unresolved > 0 && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Review {unresolved} remaining question{unresolved === 1 ? "" : "s"} before
          publishing. Approve all approves every valid pending question, including AI-flagged ones; only invalid answer formats are skipped.
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
                      documentFigures={documentFigures}
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
