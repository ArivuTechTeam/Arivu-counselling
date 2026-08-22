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
import { ExamConfig, getExamConfig, startExam } from "@/lib/api";

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-xl bg-white/10 p-4 text-center">
      <div className="text-2xl font-extrabold">{value}</div>
      <div className="mt-1 text-[11px] uppercase tracking-widest text-white/60">
        {label}
      </div>
    </div>
  );
}

export default function ExamPage() {
  const router = useRouter();
  const [cfg, setCfg] = useState<ExamConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getExamConfig()
      .then(setCfg)
      .catch((e) => setError(e.message));
  }, []);

  async function begin() {
    setBusy(true);
    setError(null);
    try {
      const { session_id } = await startExam();
      router.push(`/dashboard/student/practice/${session_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the exam.");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <PageHeader
        title="Exam Simulator"
        description="A full, timed exam under real conditions — the closest thing to the real day."
      />

      {/* Exam pattern */}
      <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full bg-white/10 blur-2xl" />
        <p className="relative text-[11px] font-semibold uppercase tracking-widest text-white/70">
          Today&apos;s exam pattern
        </p>
        <div className="relative mt-3 grid grid-cols-3 gap-3">
          <Stat value={cfg ? String(cfg.questions) : "—"} label="Questions" />
          <Stat
            value={cfg ? `${cfg.duration_minutes}m` : "—"}
            label="Time limit"
          />
          <Stat
            value={cfg ? `−${cfg.negative_marking}` : "—"}
            label="Per wrong"
          />
        </div>
      </div>

      {/* Rules */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Before you begin</CardTitle>
          <CardDescription>Read these — the exam runs under real rules.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          {[
            ["Timed", "The clock starts the moment you begin and the exam auto-submits when it runs out."],
            ["Negative marking", `Each wrong answer costs you ${cfg ? cfg.negative_marking : "—"} marks. Leave a question blank to score zero on it instead.`],
            ["No pausing", "Once you start you can't pause — set aside the full time and find a quiet spot."],
          ].map(([t, d]) => (
            <div key={t} className="flex gap-3 rounded-lg border p-3">
              <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-primary" />
              <p>
                <span className="font-semibold text-foreground">{t}.</span>{" "}
                <span className="text-muted-foreground">{d}</span>
              </p>
            </div>
          ))}

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="mt-2">
            <button
              onClick={begin}
              disabled={busy || !cfg}
              className="rounded-lg bg-gradient-to-b from-[#219256] to-[#15603d] px-6 py-3 text-sm font-bold text-white shadow-sm transition-transform hover:-translate-y-0.5 disabled:opacity-60"
            >
              {busy ? "Starting your exam…" : "Start the exam →"}
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
