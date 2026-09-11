"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton, SkeletonList } from "@/components/ui/skeleton";
import { AttemptReadiness } from "@/components/student/attempt-readiness";
import { acceptChallenge } from "@/lib/api";
import { typeLabel } from "@/lib/format";
import { downloadCardImage } from "@/lib/share-card";
import { useStudentChallenge } from "@/lib/student-queries";

const MEDAL = ["#e8b923", "#9aa4ad", "#c17d4a"]; // gold / silver / bronze

export default function ChallengeHubPage({
  params,
}: {
  params: { token: string };
}) {
  const token = params.token;
  const router = useRouter();
  const { data: info, error: loadError, mutate } = useStudentChallenge(token);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showReadiness, setShowReadiness] = useState(false);
  const [copied, setCopied] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

  async function copyLink() {
    setActionError(null);
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setActionError("Could not copy the link. Copy the address from your browser instead.");
    }
  }

  async function accept() {
    setBusy(true);
    setActionError(null);
    try {
      const { session_id } = await acceptChallenge(token);
      await mutate(undefined, { revalidate: false });
      router.push(`/dashboard/student/practice/${session_id}`);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not start the challenge.");
      setShowReadiness(false);
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader
          title="Challenge"
          description="Take on a quiz shared by a classmate."
        />
        <ErrorCard
          title="Challenge unavailable"
          message={loadError.message}
          onRetry={() => void mutate()}
        />
        <Link
          href="/dashboard/student/challenge"
          className="mx-auto text-sm font-medium text-primary hover:underline"
        >
          ← Back to challenges
        </Link>
      </div>
    );
  }

  if (!info) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title="Challenge"
          description="Take on a quiz shared by a classmate."
        />
        <Skeleton className="h-56 w-full rounded-2xl" />
        <Card>
          <CardHeader>
            <CardTitle>Leaderboard</CardTitle>
            <CardDescription>Loading the scores…</CardDescription>
          </CardHeader>
          <CardContent>
            <SkeletonList rows={4} />
          </CardContent>
        </Card>
      </div>
    );
  }

  const shareUrl = typeof window !== "undefined" ? window.location.href : "";
  const shareText = `Can you beat me? Take my ${info.questions}-question quiz on ArivuPro:`;
  const waHref = `https://wa.me/?text=${encodeURIComponent(`${shareText} ${shareUrl}`)}`;

  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/dashboard/student/challenge"
        className="w-fit text-sm font-medium text-muted-foreground transition-colors hover:text-primary"
      >
        ← Back to my challenges
      </Link>
      <PageHeader
        title="Challenge"
        description={`${info.questions} questions · ${
          info.duration_minutes
            ? `${info.duration_minutes} min`
            : "untimed legacy challenge"
        } · ${info.subject_name ?? "mixed subjects"} · created by ${info.creator_name}`}
      />

      {Object.keys(info.type_counts).length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label="Challenge question mix">
          {Object.entries(info.type_counts).map(([questionType, amount]) => (
            <span
              key={questionType}
              className="rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-xs font-medium text-primary"
            >
              {amount} {typeLabel(questionType)}
            </span>
          ))}
        </div>
      )}

      {actionError && (
        <p className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {actionError}
        </p>
      )}

      {/* Not done yet → invite to play / continue */}
      {info.my_status !== "done" && (
        <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-8 text-center text-white shadow-lg">
          <div className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full bg-white/10 blur-2xl" />
          <div className="relative">
            <h2 className="text-2xl font-bold">
              {info.my_status === "in_progress"
                ? "You have a quiz in progress"
                : info.accepting_closed && !info.is_creator
                  ? "This challenge is closed"
                : info.is_creator
                  ? "Ready to set the score?"
                  : `${info.creator_name} challenged you!`}
            </h2>
            <p className="mx-auto mt-2 max-w-md text-sm text-white/80">
              {info.my_status === "in_progress"
                ? "Pick up where you left off and lock in your score."
                : info.accepting_closed && !info.is_creator
                  ? "New attempts are no longer available. Completed scores remain on the leaderboard."
                : "Same questions for everyone — score higher than the rest to top the leaderboard."}
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {info.my_status === "in_progress" || info.is_creator || !info.accepting_closed ? (
                <button
                  onClick={() =>
                    info.my_status === "in_progress" && info.my_session_id
                      ? router.push(`/dashboard/student/practice/${info.my_session_id}`)
                      : setShowReadiness(true)
                  }
                  disabled={busy}
                  className="inline-flex items-center gap-2 rounded-lg bg-white px-6 py-2.5 text-sm font-bold text-[#15603d] shadow-md transition-transform hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {busy && (
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#15603d]/30 border-t-[#15603d]" />
                  )}
                  {busy
                    ? "Opening…"
                    : info.my_status === "in_progress"
                      ? "Continue game →"
                      : "Start my attempt →"}
                </button>
              ) : null}
              {!info.accepting_closed && (
                <button
                  type="button"
                  onClick={() => void copyLink()}
                  className="rounded-lg border border-white/30 bg-white/10 px-6 py-2.5 text-sm font-bold text-white transition-colors hover:bg-white/20"
                >
                  {copied ? "Invite link copied" : "Copy invite link"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Done → a shareable "beat my score" invite card */}
      {info.my_status === "done" && (
        <div className="flex animate-rise flex-col items-center gap-3">
          {/* Captured as the shareable image */}
          <div
            ref={cardRef}
            className="w-[340px] max-w-full overflow-hidden rounded-3xl p-7 text-center text-white shadow-2xl"
            style={{ background: "linear-gradient(150deg,#0f1f17,#17402a 55%,#0f1f17)" }}
          >
            <div className="text-sm font-black tracking-tight">
              Arivu<span style={{ color: "#7ae582" }}>PRO</span>
            </div>
            <div className="mt-1 text-[11px] uppercase tracking-widest text-white/40">
              Challenge
            </div>
            <div
              className="mx-auto mt-4 flex h-28 w-28 flex-col items-center justify-center rounded-full text-[34px] font-extrabold"
              style={{
                border: `4px solid ${(info.my_pct ?? 0) >= 60 ? "#7ae582" : (info.my_pct ?? 0) >= 40 ? "#e6a817" : "#60a5fa"}`,
                color: (info.my_pct ?? 0) >= 60 ? "#7ae582" : (info.my_pct ?? 0) >= 40 ? "#e6a817" : "#60a5fa",
              }}
            >
              {info.my_pct}%
            </div>
            <div className="mt-4 text-xl font-extrabold">I scored {info.my_pct}%</div>
            <div className="mt-1 text-sm text-white/70">Think you can beat me?</div>
            <div className="mt-4 flex items-center justify-center gap-3 text-[11px] text-white/50">
              <span>{info.questions} questions</span>
              <span>·</span>
              <span>
                {info.leaderboard.length} played
              </span>
            </div>
            <div className="mt-5 text-[10px] tracking-wide text-white/30">
              arivupro.com · take the challenge
            </div>
          </div>

          {/* Actions — outside the captured card */}
          <div className="grid w-[340px] max-w-full grid-cols-2 gap-2">
            <button
              onClick={() =>
                cardRef.current &&
                downloadCardImage(cardRef.current, `arivupro-challenge-${info.my_pct}.png`)
              }
              className="flex-1 rounded-lg border border-input bg-card px-3 py-2.5 text-sm font-semibold text-foreground shadow-sm transition-colors hover:bg-accent"
            >
              Download
            </button>
            <button
              type="button"
              onClick={() => void copyLink()}
              className="rounded-lg border border-input bg-card px-3 py-2.5 text-sm font-semibold text-foreground shadow-sm transition-colors hover:bg-accent"
            >
              {copied ? "Link copied" : "Copy link"}
            </button>
            <a
              href={waHref}
              target="_blank"
              rel="noopener noreferrer"
              className="col-span-2 rounded-lg bg-[#25D366] px-3 py-2.5 text-center text-sm font-semibold text-white transition-transform hover:-translate-y-0.5"
            >
              Share on WhatsApp
            </a>
          </div>
        </div>
      )}

      {/* Leaderboard */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Leaderboard</CardTitle>
          <CardDescription>
            {info.leaderboard.length === 0
              ? "No one has finished yet — be the first."
              : "Highest score first; faster completion breaks equal-score ties."}
          </CardDescription>
        </CardHeader>
        {info.leaderboard.length > 0 && (
          <CardContent className="flex flex-col gap-2">
            {info.leaderboard.map((r, i) => (
              <div
                key={r.rank}
                className={`flex items-center gap-3 rounded-lg border p-3 transition-colors hover:bg-accent ${
                  r.is_you ? "border-primary/40 bg-primary/5" : ""
                }`}
              >
                <span
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                  style={{ background: i < 3 ? MEDAL[i] : "#cbd5e1" }}
                >
                  {r.rank}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                  {r.name}
                  {r.is_you && (
                    <span className="ml-2 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                      You
                    </span>
                  )}
                  {r.is_creator && (
                    <span className="ml-1.5 rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                      Creator
                    </span>
                  )}
                </span>
                <div className="shrink-0 text-right">
                  <p className="text-sm font-bold text-foreground">{r.pct}%</p>
                  {r.elapsed_seconds !== null && (
                    <p className="text-[10px] text-muted-foreground">
                      {Math.floor(r.elapsed_seconds / 60)}m {r.elapsed_seconds % 60}s
                    </p>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        )}
      </Card>

      <AttemptReadiness
        open={showReadiness}
        title={`${info.creator_name}'s challenge`}
        questionCount={info.questions}
        timeLimitMinutes={info.duration_minutes}
        warningText="You can take this challenge only once. The timer begins after confirmation. Leaving ends the attempt, grades saved answers, and gives zero for unanswered questions."
        busy={busy}
        onCancel={() => setShowReadiness(false)}
        onConfirm={() => void accept()}
      />
    </div>
  );
}
