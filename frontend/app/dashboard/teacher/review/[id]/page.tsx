"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton, SkeletonCards } from "@/components/ui/skeleton";
import { SparkBurst } from "@/components/ui/spark-burst";
import { useToast } from "@/components/ui/toast";
import { QuestionPaperButtons } from "@/components/shared/pdf-buttons";
import { QuestionReviewCard } from "@/components/teacher/question-review-card";
import { QuestionReviewNavigator } from "@/components/teacher/question-review-navigator";
import { BlueprintPanel } from "@/components/teacher/blueprint-panel";
import { AssignBatchesDialog } from "@/components/teacher/assign-batches-dialog";
import { useDashboardIdentity } from "@/components/shared/dashboard-identity-context";
import { statusLabel, variantLabel } from "@/lib/format";
import {
  DocumentFigure,
  Batch,
  QuizSetDetail,
  ReviewQuestion,
  ScoringPolicy,
  archiveQuizSet,
  approveAllQuestions,
  blueprintPublish,
  regenerateQuizSet,
  getFacultyJob,
  getQuizSet,
  listDocumentFigures,
  publishQuizSet,
  duplicateQuizSet,
  listScoringPolicies,
  setQuizScoringPolicy,
  listEligibleBatches,
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

export default function ReviewDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const pathname = usePathname();
  const publishedView = pathname.startsWith("/dashboard/teacher/published-quizzes/");
  const { features } = useDashboardIdentity();
  const { notify } = useToast();
  const [detail, setDetail] = useState<QuizSetDetail | null>(null);
  const [documentFigures, setDocumentFigures] = useState<DocumentFigure[]>([]);
  const [error, setError] = useState<string | null>(null);
  const copyKey = useRef<string | null>(null);
  // Keyboard filter shortcuts: a stable window listener calls the latest handler
  // via this ref (the handler needs `chooseFilter`, which is defined after the
  // early returns, so we can't reference it directly in the effect).
  const keyHandlerRef = useRef<(e: KeyboardEvent) => void>(() => {});
  const [copying, setCopying] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [confirmPurge, setConfirmPurge] = useState(false);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [selectedBatches, setSelectedBatches] = useState<string[]>([]);
  const [batchesLoading, setBatchesLoading] = useState(false);
  const [batchesError, setBatchesError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [confirmRegen, setConfirmRegen] = useState(false);
  const [assigning, setAssigning] = useState(false);
  // Blueprint: the current random pick + whether the list is filtered to it.
  const [blueprintSelection, setBlueprintSelection] = useState<string[]>([]);
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [activeQuestionId, setActiveQuestionId] = useState<string | null>(null);
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [scoringPolicies, setScoringPolicies] = useState<ScoringPolicy[]>([]);
  const [savingPolicy, setSavingPolicy] = useState(false);
  // One-shot spark burst on the big "win" actions (publish / approve-all).
  const [celebrate, setCelebrate] = useState(false);

  useEffect(() => {
    setBatches([]);
    setSelectedBatches([]);
    setBatchesError(null);
  }, [id]);

  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(
        `teacher-review-filter:${id}`,
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
  }, [id]);

  useEffect(() => {
    if (!features.batches || detail?.status !== "draft") return;
    let cancelled = false;
    setBatchesLoading(true);
    setBatchesError(null);
    listEligibleBatches(id)
      .then((rows) => { if (!cancelled) setBatches(rows); })
      .catch((reason) => { if (!cancelled) setBatchesError(reason instanceof Error ? reason.message : "Could not load eligible batches."); })
      .finally(() => { if (!cancelled) setBatchesLoading(false); });
    return () => { cancelled = true; };
  }, [detail?.status, features.batches, id]);

  useEffect(() => {
    if (detail?.status === "published" && !publishedView) router.replace(`/dashboard/teacher/published-quizzes/${id}`);
    if (detail && detail.status !== "published" && publishedView) router.replace(`/dashboard/teacher/review/${id}`);
  }, [detail, id, publishedView, router]);

  useEffect(() => {
    if (!features.scoring_policies) return;
    listScoringPolicies().then(setScoringPolicies).catch(() => setScoringPolicies([]));
  }, [features.scoring_policies]);

  async function changeScoringPolicy(policyId: string) {
    if (!detail) return;
    setSavingPolicy(true);
    setError(null);
    try {
      const result = await setQuizScoringPolicy(id, policyId || null);
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
    getQuizSet(id)
      .then(setDetail)
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setDetail(null);
    getQuizSet(id)
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

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

  // One stable keydown listener that delegates to the latest handler.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => keyHandlerRef.current(e);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Stable list for the blueprint panel (id + type), recomputed only when the
  // quiz detail changes — so reporting the selection back can't loop.
  const blueprintQuestions = useMemo(
    () =>
      (detail?.variants ?? [])
        .flatMap((v) => v.questions)
        .map((q) => ({ id: q.id, paper_type: q.paper_type ?? null })),
    [detail],
  );

  const handleBlueprintSelection = useCallback((ids: string[]) => {
    setBlueprintSelection(ids);
  }, []);

  function openSelectedView() {
    setShowSelectedOnly(true);
    window.requestAnimationFrame(() => {
      document
        .getElementById("review-question-list")
        ?.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

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
    const storageKey = `quiz-copy-intent:${id}`;
    try { copyKey.current = window.sessionStorage.getItem(storageKey); } catch { /* retry still retains the in-memory key */ }
    copyKey.current ??= crypto.randomUUID();
    try { window.sessionStorage.setItem(storageKey, copyKey.current); } catch { /* storage may be unavailable */ }
    try {
      const copied = await duplicateQuizSet(id, `Copy of ${detail.title}`.slice(0, 200), copyKey.current);
      try { window.sessionStorage.removeItem(storageKey); } catch { /* copy already saved */ }
      copyKey.current = null;
      router.push(`/dashboard/teacher/review/${copied.quiz_set_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not duplicate the quiz. Retry to recover the same draft.");
    } finally { setCopying(false); }
  }

  // Publish gate: when purge mode is on and the teacher has marked questions
  // rejected, confirm first — publishing permanently deletes them. Otherwise
  // publish straight away, exactly as before.
  function handlePublish() {
    const purgeMode = features?.rejected_purge ?? false;
    const rejectedNow = (detail?.variants.flatMap((v) => v.questions) ?? []).filter(
      (q) => q.review_status === "rejected",
    ).length;
    if (purgeMode && rejectedNow > 0) {
      setConfirmPurge(true);
      return;
    }
    void doPublish();
  }

  async function doPublish() {
    setConfirmPurge(false);
    setError(null);
    setPublishing(true);
    try {
      if (features.batches && selectedBatches.length === 0) {
        setError("Select at least one batch before publishing this quiz.");
        return;
      }
      const s = await publishQuizSet(id, detail?.publication_token, features.batches ? selectedBatches : undefined);
      setDetail((d) => d ? {
        ...d, status: s.status,
        release_locked: d.reuse_enabled ? true : d.release_locked,
        variants: d.reuse_enabled ? d.variants.map((v) => ({
          ...v, questions: v.questions.map((q) => ({ ...q, release_locked: true })),
        })) : d.variants,
      } : d);
      // Rejected questions were permanently removed on the server; refresh so
      // they disappear from the list too.
      const removed = s.purged_rejected ?? 0;
      if (removed > 0) setDetail(await getQuizSet(id));
      celebrateBurst();
      notify(
        removed > 0
          ? `🎉 Quiz published — ${removed} rejected question${removed === 1 ? "" : "s"} removed`
          : "🎉 Quiz published — students can now see it",
        "success",
      );
      router.replace(`/dashboard/teacher/published-quizzes/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Publish failed");
    } finally {
      setPublishing(false);
    }
  }

  // Blueprint publish: publish ONLY the selected subset; the rest stay saved.
  async function handleBlueprintPublish(selectedIds: string[]) {
    if (selectedIds.length === 0) return;
    setError(null);
    setPublishing(true);
    try {
      if (!detail?.publication_token) {
        setError("Refresh the quiz before publishing this blueprint.");
        return;
      }
      if (features.batches && selectedBatches.length === 0) {
        setError("Select at least one batch before publishing this quiz.");
        return;
      }
      const s = await blueprintPublish(
        id,
        selectedIds,
        detail.publication_token,
        features.batches ? selectedBatches : undefined,
      );
      setDetail(await getQuizSet(id));
      celebrateBurst();
      notify(
        `🎉 Published ${s.published_count} question${s.published_count === 1 ? "" : "s"} — duplicate this quiz to reuse the saved questions`,
        "success",
      );
      router.replace(`/dashboard/teacher/published-quizzes/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Publish failed");
    } finally {
      setPublishing(false);
    }
  }

  async function handleRegenerateAll() {
    setConfirmRegen(false);
    setError(null);
    setRegenerating(true);
    try {
      let job = await regenerateQuizSet(id);
      notify("Regeneration was queued. It will continue even if you leave this page.", "success");
      while (job.status === "queued" || job.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 2_000));
        job = await getFacultyJob(job.id);
      }
      if (job.status !== "completed" || !job.result) {
        throw new Error(job.error_message || "Regeneration did not complete. Check Recent tasks and try again.");
      }
      const r = {
        regenerated: job.result.regenerated ?? 0,
        kept: job.result.kept ?? 0,
        total: job.result.total ?? 0,
      };
      setDetail(await getQuizSet(id));
      celebrateBurst();
      notify(
        r.kept > 0
          ? `Regenerated ${r.regenerated} of ${r.total} questions (${r.kept} kept their previous version)`
          : `🎉 Regenerated all ${r.regenerated} questions — review them below`,
        "success",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Regeneration failed");
    } finally {
      setRegenerating(false);
    }
  }

  async function handleApproveAll() {
    setError(null);
    setApproving(true);
    try {
      const { approved: count, skipped = 0 } = await approveAllQuestions(id);
      if (skipped) setError(`${skipped} question(s) need an answer-format correction or changed during approval. Open them to check.`);
      setDetail(await getQuizSet(id));
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
      await archiveQuizSet(id);
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
  const selectedSet = new Set(blueprintSelection);
  const visibleVariants = detail.variants
    .map((variant) => ({
      ...variant,
      questions: showSelectedOnly
        ? variant.questions.filter((question) => selectedSet.has(question.id))
        : reviewFilter === "all"
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
      window.sessionStorage.setItem(`teacher-review-filter:${id}`, filter);
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

  // Filter shortcuts: A/P/R/E to filter by status, 0 for all. Ignored while
  // typing in a field so it never fights with editing a question.
  keyHandlerRef.current = (e: KeyboardEvent) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const el = e.target as HTMLElement | null;
    const tag = el?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el?.isContentEditable) return;
    const map: Record<string, ReviewFilter> = {
      a: "approved",
      p: "pending_review",
      r: "rejected",
      e: "needs_edit",
      "0": "all",
    };
    const next = map[e.key.toLowerCase()];
    if (next) {
      e.preventDefault();
      chooseFilter(next);
    }
  };

  return (
    <div className="mx-auto flex h-full max-w-7xl flex-col gap-4">
      <div className="sticky top-0 z-[9] -mx-1 bg-background/95 px-1 pb-3 backdrop-blur supports-[backdrop-filter]:bg-background/85">
        <div className="animate-rise relative overflow-hidden rounded-2xl border bg-card shadow-sm">
          {celebrate && <SparkBurst count={24} />}

          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-5">
            <div className="min-w-0">
              <Link
                href={publishedView ? "/dashboard/teacher/published-quizzes" : "/dashboard/teacher/review"}
                className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                ← {publishedView ? "Published quizzes" : "Review queue"}
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
              quizSetId={id}
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
              <span
                className="ml-1 hidden shrink-0 select-none items-center self-center rounded-md border border-dashed border-input px-2 text-[10px] font-medium text-muted-foreground lg:inline-flex"
                title="Keyboard: A approved · P pending · R rejected · E needs edit · 0 all"
              >
                ⌨ A / P / R / E / 0
              </span>
            </div>

            <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
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
            <Link href={`/dashboard/teacher/performance/${id}`}>
              <Button size="sm" variant="outline">View performance</Button>
            </Link>
          )}
          {features.batches && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setAssigning(true)}
              disabled={archiving || publishing || approving}
            >
              Assign to batches
            </Button>
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
          {features.regenerate_set && detail.status === "draft" && all.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setConfirmRegen(true)}
              disabled={regenerating || approving || publishing || detail.release_locked}
            >
              {regenerating ? "Regenerating…" : "Regenerate quiz"}
            </Button>
          )}
          {approvablePending > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleApproveAll}
              disabled={approving || publishing || regenerating || detail.release_locked}
            >
              {approving ? "Approving…" : `Approve all (${approvablePending})`}
            </Button>
          )}
          <Button
            size="sm"
            onClick={handlePublish}
            disabled={publishing || copying || detail.status === "published" || detail.status === "archived" || unresolved > 0 || (features.batches && (batchesLoading || !!batchesError || selectedBatches.length === 0))}
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
      {features.batches && detail.status === "draft" && (
        <section className="rounded-xl border bg-card p-4" aria-label="Assign batches before publishing">
          <h2 className="font-semibold">Assign to batches</h2>
          <p className="mt-1 text-sm text-muted-foreground">Choose the batches that can take this quiz. Only these batches will see it after publication.</p>
          {batchesLoading ? <p className="mt-3 text-sm">Loading eligible batches…</p> : batchesError ? (
            <p role="alert" className="mt-3 text-sm text-destructive">{batchesError}</p>
          ) : batches.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">No eligible batches are available. Ask your institution admin to create or assign an active batch for this course and level.</p>
          ) : (
            <div className="mt-3 flex flex-wrap gap-2">
              {batches.map((batch) => (
                <label key={batch.id} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm">
                  <input type="checkbox" checked={selectedBatches.includes(batch.id)} onChange={(event) => setSelectedBatches((current) => event.target.checked ? [...current, batch.id] : current.filter((id) => id !== batch.id))} />
                  {batch.name}
                </label>
              ))}
            </div>
          )}
        </section>
      )}
      {/* A concise import receipt only when some candidates were skipped, so the
          review stays focused on the questions. The verbose source-inventory /
          "not matched" coverage report is intentionally not shown here. */}
      {detail.import_summaries?.filter((summary) => summary.skipped > 0).map((summary) => (
        <details key={summary.extraction_job_id}
          className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <summary className="cursor-pointer font-medium">
            Import receipt: {summary.imported} imported, {summary.skipped} skipped
          </summary>
          {summary.issues.map((issue) => (
            <p key={issue.candidate_index} className="mt-2">
              Candidate {issue.candidate_index}: {issue.question_preview || "Unreadable question"}
              {" — "}{issue.reason}
            </p>
          ))}
        </details>
      ))}
      {detail.status !== "published" && unresolved > 0 && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Review {unresolved} remaining question{unresolved === 1 ? "" : "s"} before
          publishing. Approve all approves every valid pending question, including AI-flagged ones; only invalid answer formats are skipped.
        </p>
      )}

      {features.extraction_blueprint && detail.status === "draft" && all.length > 0 && (
        <BlueprintPanel
          questions={blueprintQuestions}
          publishing={publishing}
          previewing={showSelectedOnly}
          onPublish={handleBlueprintPublish}
          onSelectionChange={handleBlueprintSelection}
          onPreview={openSelectedView}
        />
      )}

      {showSelectedOnly && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/30 bg-primary/10 px-3 py-2 text-sm">
          <span className="font-medium text-primary">
            Showing the {selectedSet.size} question{selectedSet.size === 1 ? "" : "s"} you&apos;re about
            to publish. Read or edit them, shuffle for a different set, then publish.
          </span>
          <Button size="sm" variant="outline" onClick={() => setShowSelectedOnly(false)}>
            Show all questions
          </Button>
        </div>
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

      {assigning && (
        <AssignBatchesDialog
          quizSetId={id}
          quizTitle={detail.title}
          onClose={() => setAssigning(false)}
        />
      )}

      {confirmRegen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="regen-confirm-title"
          onClick={() => !regenerating && setConfirmRegen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border bg-card p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="regen-confirm-title" className="text-lg font-semibold tracking-tight">
              Regenerate all {all.length} question{all.length === 1 ? "" : "s"}?
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Every question is replaced with a <strong>fresh AI version</strong> of the same type,
              and your review resets to pending. This <strong>can&apos;t be undone</strong>. It may
              take a little while.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setConfirmRegen(false)} disabled={regenerating}>
                Cancel
              </Button>
              <Button onClick={() => void handleRegenerateAll()} disabled={regenerating}>
                {regenerating ? "Regenerating…" : "Yes, regenerate all"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {confirmPurge && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="purge-confirm-title"
          onClick={() => !publishing && setConfirmPurge(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border bg-card p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="purge-confirm-title" className="text-lg font-semibold tracking-tight">
              Delete {rejected} rejected question{rejected === 1 ? "" : "s"}?
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              You have rejected <strong>{rejected}</strong> question{rejected === 1 ? "" : "s"}.
              If you publish now, {rejected === 1 ? "it" : "they"} will be{" "}
              <strong>deleted permanently</strong>. Approved questions will be published as usual.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setConfirmPurge(false)}
                disabled={publishing}
              >
                No, go back
              </Button>
              <Button onClick={() => void doPublish()} disabled={publishing}>
                {publishing ? "Publishing…" : "Yes, publish & delete"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
