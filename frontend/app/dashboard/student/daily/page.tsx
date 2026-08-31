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

// Fixed calendar week, always Sunday → Saturday.
const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

/** Shift an ISO date (yyyy-mm-dd) by `days`, returning a new ISO date. */
function isoShift(iso: string, days: number): string {
  const dt = new Date(`${iso}T00:00:00`);
  dt.setDate(dt.getDate() + days);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const d = String(dt.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** Day-of-month number, e.g. "2026-08-31" → 31. */
function dayNum(iso: string): number {
  return new Date(`${iso}T00:00:00`).getDate();
}

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

  // The server's last7 ends on "today" — anchor the calendar week on it so the
  // grid is a real Sunday→Saturday week, not a rolling window.
  const anchor = info.last7[info.last7.length - 1].date;
  const doneMap = new Map(info.last7.map((d) => [d.date, d.done]));
  const todayDow = new Date(`${anchor}T00:00:00`).getDay();
  const weekStart = isoShift(anchor, -todayDow); // Sunday of this week

  const week = Array.from({ length: 7 }, (_, i) => {
    const date = isoShift(weekStart, i);
    return {
      date,
      label: WEEKDAYS[i],
      num: dayNum(date),
      done: doneMap.get(date) ?? false,
      isToday: date === anchor,
      isFuture: date > anchor,
    };
  });
  const doneThisWeek = week.filter((w) => w.done).length;

  const cheer =
    info.streak >= 7
      ? "You're on fire — incredible discipline! 🔥"
      : info.streak >= 3
        ? "You're on a roll. Keep the momentum going!"
        : info.streak >= 1
          ? "Nice start — come back daily to build it up."
          : "Take today's challenge to start your streak.";

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Daily Challenge"
        description="A fresh 10-question quiz every day — keep your streak alive. 🔥"
      />

      {/* Streak hero */}
      <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 animate-pulse rounded-full bg-white/10 blur-3xl" />

        <div className="relative flex flex-wrap items-center justify-between gap-6">
          {/* Current streak */}
          <div className="flex items-center gap-3">
            <span
              className="text-5xl leading-none sm:text-6xl"
              style={{ filter: "drop-shadow(0 0 14px rgba(255,170,60,0.55))" }}
            >
              🔥
            </span>
            <div className="flex items-end gap-2">
              <span className="text-5xl font-extrabold leading-none text-[#9ff0a6] sm:text-6xl">
                {info.streak}
              </span>
              <span className="pb-1 text-xs font-semibold uppercase tracking-widest text-white/70">
                day
                <br />
                streak
              </span>
            </div>
          </div>

          {/* Mini stats */}
          <div className="flex gap-3">
            <div className="rounded-xl bg-white/10 px-4 py-3 text-center backdrop-blur-sm">
              <div className="text-lg font-bold text-white">
                🏆 {info.longest}
              </div>
              <div className="mt-0.5 text-[10px] uppercase tracking-wider text-white/60">
                Longest
              </div>
            </div>
            <div className="rounded-xl bg-white/10 px-4 py-3 text-center backdrop-blur-sm">
              <div className="text-lg font-bold text-white">
                📅 {doneThisWeek}/7
              </div>
              <div className="mt-0.5 text-[10px] uppercase tracking-wider text-white/60">
                This week
              </div>
            </div>
          </div>
        </div>

        <p className="relative mt-4 text-sm font-medium text-white/85">{cheer}</p>

        {/* This week — fixed Sunday → Saturday */}
        <div className="relative mt-6">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-white/50">
            This week
          </div>
          <div className="grid grid-cols-7 gap-1.5 sm:gap-2">
            {week.map((d) => {
              const base =
                "flex h-10 w-full items-center justify-center rounded-xl text-xs font-bold transition-transform hover:scale-110";
              const state = d.done
                ? "bg-[#7ae582] text-[#0f1f17] shadow-sm"
                : d.isToday
                  ? "bg-white/20 text-white ring-2 ring-white/80"
                  : d.isFuture
                    ? "bg-white/5 text-white/25"
                    : "bg-white/10 text-white/40";
              return (
                <div key={d.date} className="flex flex-col items-center gap-1.5">
                  <span
                    className={`text-[10px] font-semibold uppercase ${
                      d.isToday ? "text-white" : "text-white/45"
                    }`}
                  >
                    {d.label}
                  </span>
                  <div
                    className={`${base} ${state} ${
                      d.isToday && !d.done ? "animate-pulse" : ""
                    }`}
                    title={d.done ? "Completed" : d.isToday ? "Today" : ""}
                  >
                    {d.done ? "✓" : d.num}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Today's action */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {info.done_today ? "Today's challenge 🎉" : "Today's challenge"}
          </CardTitle>
          <CardDescription>
            {info.done_today
              ? "You've completed today's challenge — come back tomorrow to keep the streak going."
              : "10 quick questions from your syllabus. Finish to extend your streak."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {/* Info chips */}
          <div className="flex flex-wrap gap-2 text-xs font-medium">
            <span className="rounded-full bg-muted px-3 py-1 text-muted-foreground">
              🎯 10 questions
            </span>
            <span className="rounded-full bg-muted px-3 py-1 text-muted-foreground">
              ⏱️ ~5 minutes
            </span>
            <span className="rounded-full bg-primary/10 px-3 py-1 text-primary">
              🔥 +1 to your streak
            </span>
          </div>

          {info.done_today ? (
            <div className="flex items-center gap-3 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 text-sm font-medium text-primary">
              <span className="text-lg">✅</span>
              <span>
                Done for today — see you tomorrow to keep your{" "}
                <strong>{info.streak}-day</strong> streak alive!
              </span>
            </div>
          ) : (
            <button
              onClick={start}
              disabled={busy}
              className="w-fit rounded-xl bg-gradient-to-b from-[#219256] to-[#15603d] px-6 py-3 text-sm font-semibold text-white shadow-md transition-transform hover:-translate-y-0.5 disabled:opacity-60"
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
