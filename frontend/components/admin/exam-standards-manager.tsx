"use client";

import { useCallback, useEffect, useState } from "react";

import {
  CourseExamStandard,
  ScoringPreset,
  listExamStandards,
  listScoringPresets,
  setExamStandard,
} from "@/lib/api";

const field =
  "h-11 w-full max-w-md rounded-lg border border-input bg-background px-3 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-50";

export function ExamStandardsManager() {
  const [presets, setPresets] = useState<ScoringPreset[]>([]);
  const [rows, setRows] = useState<CourseExamStandard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [p, r] = await Promise.all([listScoringPresets(), listExamStandards()]);
      setPresets(p);
      setRows(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load exam standards.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const describe = (key: string | null) =>
    presets.find((p) => p.key === key)?.description ?? "";

  async function change(courseLevelId: string, key: string) {
    setSaving(courseLevelId);
    setError(null);
    const value = key || null;
    try {
      await setExamStandard(courseLevelId, value);
      setRows((rs) => rs.map((r) => (r.course_level_id === courseLevelId ? { ...r, preset_key: value } : r)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the exam standard.");
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Exam standards</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose how the <strong>exam simulator</strong> scores each course level — the official
          marking rule of that exam (e.g. CA Foundation deducts 0.25 per wrong answer, CMA
          deducts nothing). Normal practice quizzes are unaffected.
        </p>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="rounded-xl border border-dashed bg-card/60 p-6 text-center text-sm text-muted-foreground">
          No courses yet. Create a course first.
        </p>
      ) : (
        <div className="grid gap-3">
          {rows.map((row) => (
            <div key={row.course_level_id} className="rounded-xl border bg-card p-4 shadow-sm">
              <p className="mb-2 font-semibold">{row.course_name} · {row.level_name}</p>
              <select
                className={field}
                value={row.preset_key ?? ""}
                disabled={saving === row.course_level_id}
                onChange={(e) => change(row.course_level_id, e.target.value)}
              >
                <option value="">Standard — no negative marking (default)</option>
                {presets
                  .filter((p) => p.key !== "standard")
                  .map((p) => (
                    <option key={p.key} value={p.key}>{p.name}</option>
                  ))}
              </select>
              {describe(row.preset_key) && (
                <p className="mt-1.5 text-xs text-muted-foreground">{describe(row.preset_key)}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
