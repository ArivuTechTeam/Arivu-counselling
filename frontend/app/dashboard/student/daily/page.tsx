"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { DailyInfo, getDaily, startDaily } from "@/lib/api";

const DOW = ["S", "M", "T", "W", "T", "F", "S"];

export default function DailyPage() {
  const router = useRouter();
  const [info, setInfo] = useState<DailyInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDaily()
      .then(setInfo)
      .catch((e) => setError(e.message));
  }, []);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const { session_id } = await startDaily();
      router.push(`/dashboard/student/practice/${session_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start today's challenge.");
      setBusy(false);
    }
  }

  if (error) return <p className="text-red-600">{error}</p>;
  if (!info) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const dow = (iso: string) => DOW[new Date(`${iso}T00:00:00`).getDay()];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Daily Challenge"
        description="A fresh 10-question quiz every day. Do it daily to build your streak."
      />

      {/* Streak hero */}
      <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full bg-white/10 blur-2xl" />
        <div className="relative flex flex-wrap items-center justify-between gap-6">
          <div className="flex items-end gap-3">
            <span className="text-6xl font-extrabold leading-none text-[#9ff0a6]">
              {info.streak}
            </span>
            <span className="pb-1 text-sm font-semibold uppercase tracking-widest text-white/70">
              day
              <br />
              streak
            </span>
          </div>
          <div className="text-right text-xs text-white/70">
            Longest streak
            <div className="text-2xl font-bold text-white">{info.longest}</div>
          </div>
        </div>

        {/* Last 7 days */}
        <div className="relative mt-6 flex justify-between gap-2">
          {info.last7.map((d, i) => {
            const isToday = i === info.last7.length - 1;
            return (
              <div key={d.date} className="flex flex-1 flex-col items-center gap-1.5">
                <div
                  className={`flex h-9 w-full max-w-[44px] items-center justify-center rounded-lg text-xs font-bold transition-colors ${
                    d.done
                      ? "bg-[#7ae582] text-[#0f1f17]"
                      : "bg-white/10 text-white/50"
                  } ${isToday ? "ring-2 ring-white/70" : ""}`}
                >
                  {dow(d.date)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Today's action */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Today&apos;s challenge</CardTitle>
          <CardDescription>
            {info.done_today
              ? "You've completed today's challenge — come back tomorrow to keep the streak going."
              : "10 quick questions from your syllabus. Finish to extend your streak."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {info.done_today ? (
            <div className="rounded-lg border border-primary/30 bg-primary/5 px-4 py-3 text-sm font-medium text-primary">
              Done for today. See you tomorrow!
            </div>
          ) : (
            <button
              onClick={start}
              disabled={busy}
              className="rounded-lg bg-gradient-to-b from-[#219256] to-[#15603d] px-6 py-2.5 text-sm font-semibold text-white shadow-sm transition-transform hover:-translate-y-0.5 disabled:opacity-60"
            >
              {busy
                ? "Loading…"
                : info.today_session_id
                  ? "Continue today's challenge →"
                  : "Start today's challenge →"}
            </button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
