"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useSWRConfig } from "swr";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { closeChallenge, createChallenge } from "@/lib/api";
import { typeLabel } from "@/lib/format";
import {
  studentChallengeKey,
  useMyChallenges,
  usePracticeSubjects,
} from "@/lib/student-queries";

const QUESTION_TYPES = [
  "mcq_single",
  "mcq_multi",
  "true_false",
  "numerical",
  "fill_blank",
] as const;
type ChallengeQuestionType = (typeof QUESTION_TYPES)[number];
const DEFAULT_MIX: Record<ChallengeQuestionType, number> = {
  mcq_single: 4,
  mcq_multi: 1,
  true_false: 2,
  numerical: 2,
  fill_blank: 1,
};
const fieldClass =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

export default function ChallengePage() {
  const router = useRouter();
  const { mutate: mutateCache } = useSWRConfig();
  const { data: subjects = null, error: subjectsError } = usePracticeSubjects();
  const { data: mine = null, error: mineError, mutate: mutateMine } = useMyChallenges();
  const [subjectId, setSubjectId] = useState("");
  const [typeCounts, setTypeCounts] = useState(DEFAULT_MIX);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [closingToken, setClosingToken] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);
  const totalQuestions = QUESTION_TYPES.reduce(
    (total, questionType) => total + typeCounts[questionType],
    0,
  );

  function changeCount(questionType: ChallengeQuestionType, value: number) {
    const safeValue = Number.isFinite(value)
      ? Math.max(0, Math.min(100, Math.floor(value)))
      : 0;
    setTypeCounts((current) => ({ ...current, [questionType]: safeValue }));
  }

  async function copyLink(token: string) {
    setError(null);
    try {
      const url = `${window.location.origin}/dashboard/student/challenge/${token}`;
      await navigator.clipboard.writeText(url);
      setCopiedToken(token);
      window.setTimeout(
        () => setCopiedToken((current) => (current === token ? null : current)),
        1800,
      );
    } catch {
      setError("Could not copy the link. Open the challenge and copy the address from your browser.");
    }
  }

  async function create() {
    if (totalQuestions < 1 || totalQuestions > 100) {
      setError("Choose between 1 and 100 questions in total.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { token } = await createChallenge({
        subject_id: subjectId || null,
        type_counts: typeCounts,
      });
      void mutateMine();
      router.push(`/dashboard/student/challenge/${token}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the challenge.");
      setBusy(false);
    }
  }

  async function close(token: string) {
    if (!window.confirm("Close this challenge to new players? Existing scores will stay visible.")) return;
    setClosingToken(token);
    setError(null);
    try {
      await closeChallenge(token);
      await mutateCache(studentChallengeKey(token), undefined, {
        revalidate: false,
      });
      await mutateMine();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not close the challenge.");
    } finally {
      setClosingToken(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Challenge a Friend"
        description="Create a custom quiz game, share it now, and play whenever you are ready. Highest score tops the leaderboard."
      />

      {/* Hero */}
      <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full bg-white/10 blur-2xl" />
        <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">
          How it works
        </p>
        <div className="relative mt-3 grid gap-3 sm:grid-cols-3">
          {[
            ["1", "Build your game", "Choose the exact mix of question types."],
            ["2", "Share immediately", "Send the link now—playing can happen later."],
            ["3", "Play & compete", "Everyone gets the same quiz and joins one leaderboard."],
          ].map(([n, t, d]) => (
            <div key={n} className="rounded-xl bg-white/10 p-4">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-white/20 text-sm font-bold">
                {n}
              </div>
              <p className="mt-2 text-sm font-semibold">{t}</p>
              <p className="mt-1 text-xs text-white/70">{d}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Build form */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Create your challenge</CardTitle>
          <CardDescription>
            Build from teacher-approved questions. Creating the link does not
            start your attempt or its timer.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_12rem]">
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Subject
              {subjects === null ? (
                <Skeleton className="h-10 w-full rounded-md" />
              ) : (
                <select
                  className={fieldClass}
                  value={subjectId}
                  onChange={(e) => setSubjectId(e.target.value)}
                  disabled={Boolean(subjectsError)}
                >
                  <option value="">All my subjects</option>
                  {(subjects ?? []).map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              )}
              {subjectsError && (
                <span className="text-xs font-normal text-destructive">
                  Couldn&apos;t load subjects — you can still play across all of
                  them.
                </span>
              )}
            </label>
            <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-center">
              <p className="text-2xl font-bold text-primary">{totalQuestions}</p>
              <p className="text-xs text-muted-foreground">Total questions</p>
            </div>
          </div>

          <div>
            <div className="mb-2">
              <p className="text-sm font-semibold">Choose the question mix</p>
              <p className="text-xs text-muted-foreground">
                Set a type to 0 if you do not want it in this game.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              {QUESTION_TYPES.map((questionType) => (
                <label
                  key={questionType}
                  className="flex items-center justify-between gap-3 rounded-xl border bg-muted/20 px-3 py-3 sm:flex-col sm:items-stretch"
                >
                  <span className="text-sm font-medium">{typeLabel(questionType)}</span>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    inputMode="numeric"
                    value={typeCounts[questionType]}
                    onChange={(event) =>
                      changeCount(questionType, Number(event.target.value))
                    }
                    className="h-9 w-20 rounded-md border border-input bg-background px-2 text-center text-sm font-semibold focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 sm:w-full"
                    aria-label={`${typeLabel(questionType)} question count`}
                  />
                </label>
              ))}
            </div>
          </div>

          {error && (
            <p className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}

          <div>
            <button
              onClick={() => void create()}
              disabled={busy || totalQuestions < 1 || totalQuestions > 100}
              className="rounded-lg bg-gradient-to-b from-[#219256] to-[#15603d] px-6 py-2.5 text-sm font-semibold text-white shadow-sm transition-transform hover:-translate-y-0.5 disabled:opacity-60"
            >
              {busy ? "Creating game…" : "Create game link →"}
            </button>
            <p className="mt-2 text-xs text-muted-foreground">
              You can share first and start your one attempt whenever you are ready.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>My challenges</CardTitle>
          <CardDescription>
            Open a game lobby, start or continue your attempt, copy its link, or
            close it to new players.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {mineError ? (
            <p className="text-sm text-destructive">{mineError.message}</p>
          ) : mine === null ? (
            <>
              <Skeleton className="h-20 w-full rounded-xl" />
              <Skeleton className="h-20 w-full rounded-xl" />
            </>
          ) : mine.length === 0 ? (
            <p className="rounded-xl border border-dashed p-5 text-sm text-muted-foreground">
              Your created challenges will appear here.
            </p>
          ) : (
            mine.map((challenge) => {
              const closed = !challenge.is_active || challenge.is_expired;
              return (
                <div
                  key={challenge.token}
                  className="flex flex-col gap-3 rounded-xl border p-4 sm:flex-row sm:items-center"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold">
                      {challenge.subject_name ?? "Mixed subjects"}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {challenge.questions} questions · {challenge.duration_minutes
                        ? `${challenge.duration_minutes} min`
                        : "Untimed legacy challenge"} · {challenge.players} completed
                    </p>
                    <p className={`mt-1 text-xs ${closed ? "text-amber-700" : "text-primary"}`}>
                      {challenge.is_expired
                        ? "Expired"
                        : challenge.is_active
                          ? "Open to classmates"
                          : "Closed to new players"}
                      {" · "}
                      {challenge.my_status === "done"
                        ? "Your score is submitted"
                        : challenge.my_status === "in_progress"
                          ? "Your game is in progress"
                          : "You have not played yet"}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      type="button"
                      onClick={() => void copyLink(challenge.token)}
                      className="rounded-lg border border-input px-3 py-2 text-sm font-semibold hover:bg-accent"
                    >
                      {copiedToken === challenge.token ? "Copied" : "Copy link"}
                    </button>
                    <Link
                      href={`/dashboard/student/challenge/${challenge.token}`}
                      className="rounded-lg border border-input px-3 py-2 text-sm font-semibold hover:bg-accent"
                    >
                      Open
                    </Link>
                    {!closed && (
                      <button
                        type="button"
                        disabled={closingToken === challenge.token}
                        onClick={() => void close(challenge.token)}
                        className="rounded-lg border border-amber-300 px-3 py-2 text-sm font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-60"
                      >
                        {closingToken === challenge.token ? "Closing…" : "Close"}
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

    </div>
  );
}
