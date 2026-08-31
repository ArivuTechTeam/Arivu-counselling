"use client";

import { useEffect, useRef, useState } from "react";
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
import { ChallengeInfo, acceptChallenge, getChallenge } from "@/lib/api";
import { downloadCardImage } from "@/lib/share-card";

const MEDAL = ["#e8b923", "#9aa4ad", "#c17d4a"]; // gold / silver / bronze

export default function ChallengeHubPage({
  params,
}: {
  params: { token: string };
}) {
  const token = params.token;
  const router = useRouter();
  const [info, setInfo] = useState<ChallengeInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

  function load() {
    setError(null);
    setInfo(null);
    getChallenge(token)
      .then(setInfo)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [token]);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      const { session_id } = await acceptChallenge(token);
      router.push(`/dashboard/student/practice/${session_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the challenge.");
      setBusy(false);
    }
  }

  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader
          title="Challenge"
          description="Take on a quiz shared by a classmate."
        />
        <ErrorCard
          title="Challenge unavailable"
          message={error}
          onRetry={load}
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
      <PageHeader
        title="Challenge"
        description={`${info.questions} questions · created by ${info.creator_name}`}
      />

      {/* Not done yet → invite to play / continue */}
      {info.my_status !== "done" && (
        <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-8 text-center text-white shadow-lg">
          <div className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full bg-white/10 blur-2xl" />
          <div className="relative">
            <h2 className="text-2xl font-bold">
              {info.my_status === "in_progress"
                ? "You have a quiz in progress"
                : info.is_creator
                  ? "Ready to set the score?"
                  : `${info.creator_name} challenged you!`}
            </h2>
            <p className="mx-auto mt-2 max-w-md text-sm text-white/80">
              {info.my_status === "in_progress"
                ? "Pick up where you left off and lock in your score."
                : "Same questions for everyone — score higher than the rest to top the leaderboard."}
            </p>
            <button
              onClick={() =>
                info.my_status === "in_progress" && info.my_session_id
                  ? router.push(`/dashboard/student/practice/${info.my_session_id}`)
                  : accept()
              }
              disabled={busy}
              className="mt-6 inline-flex items-center gap-2 rounded-lg bg-white px-6 py-2.5 text-sm font-bold text-[#15603d] shadow-md transition-transform hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {busy && (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#15603d]/30 border-t-[#15603d]" />
              )}
              {busy
                ? "Loading…"
                : info.my_status === "in_progress"
                  ? "Continue →"
                  : "Accept challenge →"}
            </button>
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
          <div className="flex w-[340px] max-w-full gap-2">
            <button
              onClick={() =>
                cardRef.current &&
                downloadCardImage(cardRef.current, `arivupro-challenge-${info.my_pct}.png`)
              }
              className="flex-1 rounded-lg border border-input bg-card px-3 py-2.5 text-sm font-semibold text-foreground shadow-sm transition-colors hover:bg-accent"
            >
              Download
            </button>
            <a
              href={waHref}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 rounded-lg bg-[#25D366] px-3 py-2.5 text-center text-sm font-semibold text-white transition-transform hover:-translate-y-0.5"
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
              : "Everyone who's taken this challenge, highest first."}
          </CardDescription>
        </CardHeader>
        {info.leaderboard.length > 0 && (
          <CardContent className="flex flex-col gap-2">
            {info.leaderboard.map((r, i) => (
              <div
                key={i}
                className={`flex items-center gap-3 rounded-lg border p-3 transition-colors hover:bg-accent ${
                  r.is_you ? "border-primary/40 bg-primary/5" : ""
                }`}
              >
                <span
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                  style={{ background: i < 3 ? MEDAL[i] : "#cbd5e1" }}
                >
                  {i + 1}
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
                <span className="shrink-0 text-sm font-bold text-foreground">
                  {r.pct}%
                </span>
              </div>
            ))}
          </CardContent>
        )}
      </Card>
    </div>
  );
}
