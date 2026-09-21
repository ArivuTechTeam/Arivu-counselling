"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonList } from "@/components/ui/skeleton";
import { LeaderRow } from "@/lib/api";
import { useStudentLeaderboard } from "@/lib/student-queries";
import { useSessionStorageState } from "@/lib/use-session-storage-state";

const MEDAL = ["#e8b923", "#9aa4ad", "#c17d4a"]; // gold / silver / bronze

function Row({ r }: { r: LeaderRow }) {
  return (
    <div
      className={`flex items-center gap-3 rounded-lg border p-3 transition-colors hover:bg-accent ${
        r.is_you ? "border-primary/40 bg-primary/5" : ""
      }`}
    >
      <span
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
        style={{ background: r.rank <= 3 ? MEDAL[r.rank - 1] : "#cbd5e1" }}
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
      </span>
      <span className="shrink-0 text-right">
        <span className="block text-sm font-bold text-foreground">
          {r.points} pts
        </span>
        <span className="block text-[11px] text-muted-foreground">
          {r.accuracy}% · {r.quizzes} quiz{r.quizzes === 1 ? "" : "zes"}
        </span>
      </span>
    </div>
  );
}

export default function LeaderboardPage() {
  const [courseId, setCourseId] = useSessionStorageState<string | undefined>(
    "student-leaderboard-course",
    undefined,
    (value): value is string | undefined =>
      value === undefined || typeof value === "string",
  );
  const { data, error, isValidating, mutate } =
    useStudentLeaderboard(courseId);

  if (error) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <PageHeader
          title="Leaderboard"
          description="How you rank among students in your course."
        />
        <ErrorCard message={error.message} onRetry={() => void mutate()} />
      </div>
    );
  }

  const inTop = data?.me && data.top.some((r) => r.is_you);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <PageHeader
        title="Leaderboard"
        description={
          data?.course_name
            ? `How you rank among students in ${data.course_name}.`
            : "How you rank among students in your course."
        }
      />

      {/* Course switcher — only when the student is in more than one course */}
      {data && data.courses.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {data.courses.map((c) => (
            <button
              key={c.id}
              onClick={() => setCourseId(c.id)}
              disabled={isValidating}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                c.id === data.course_id
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-input text-muted-foreground hover:border-primary/40"
              }`}
            >
              {c.name}
            </button>
          ))}
        </div>
      )}

      {/* Your rank banner (always visible) */}
      {data?.me && (
        <div className="animate-rise flex items-center justify-between rounded-2xl bg-gradient-to-br from-[#1a6942] to-[#15603d] p-5 text-white shadow-lg">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">
              Your rank
            </p>
            <p className="mt-1 text-3xl font-extrabold">
              #{data.me.rank}
              <span className="ml-2 text-sm font-medium text-white/70">
                of {data.total}
              </span>
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold text-[#9ff0a6]">{data.me.points} pts</p>
            <p className="text-xs text-white/70">{data.me.accuracy}% accuracy</p>
          </div>
        </div>
      )}

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>
            Top students{data?.course_name ? ` · ${data.course_name}` : ""}
          </CardTitle>
          <CardDescription>
            {!data
              ? "Fetching the latest scores…"
              : data.top.length === 0
                ? "No quiz results yet for this course — take a quiz to get on the board."
                : "Points are based on your total score across quizzes. Keep practising to climb."}
          </CardDescription>
        </CardHeader>
        {!data && (
          <CardContent>
            <SkeletonList rows={6} />
          </CardContent>
        )}
        {data && data.top.length > 0 && (
          <CardContent className="flex flex-col gap-2">
            {data.top.map((r) => (
              <Row key={r.rank} r={r} />
            ))}
            {/* If you're outside the top 20, pin your own row below. */}
            {data.me && !inTop && (
              <>
                <div className="relative py-3 text-center">
                  <span className="absolute inset-x-0 top-1/2 border-t border-dashed border-input" />
                  <span className="relative bg-card px-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                    Your position
                  </span>
                </div>
                <Row r={data.me} />
              </>
            )}
          </CardContent>
        )}
      </Card>
    </div>
  );
}
