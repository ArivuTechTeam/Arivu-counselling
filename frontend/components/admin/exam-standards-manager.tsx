"use client";

import { useCallback, useEffect, useState } from "react";

import {
  CourseExamStandard,
  ScoringPolicy,
  ScoringPreset,
  createScoringPolicy,
  listExamStandards,
  listScoringPolicies,
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
  const [policies, setPolicies] = useState<ScoringPolicy[]>([]);
  const [policyName, setPolicyName] = useState("");
  const [wrongPenalty, setWrongPenalty] = useState("0");
  const [fractionalPenalty, setFractionalPenalty] = useState(false);
  const [partialCredit, setPartialCredit] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [p, r, custom] = await Promise.all([
        listScoringPresets(), listExamStandards(), listScoringPolicies(),
      ]);
      setPresets(p);
      setRows(r);
      setPolicies(custom);
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

  async function createPolicy(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const created = await createScoringPolicy({
        name: policyName.trim(),
        wrong_penalty: Number(wrongPenalty),
        penalty_is_fraction: fractionalPenalty,
        omission_score: 0,
        multi_mode: partialCredit ? "mrm_partial" : "all_or_nothing",
        clamp_negative_total: true,
      });
      setPolicies((current) => [...current, created].sort((a, b) => a.name.localeCompare(b.name)));
      setPolicyName("");
      setWrongPenalty("0");
      setFractionalPenalty(false);
      setPartialCredit(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create the scoring policy.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Exam standards</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose how the <strong>exam simulator</strong> scores each course level — the official
          marking rule of that exam (e.g. CA Foundation deducts 0.25 per wrong answer, CMA
          deducts nothing). Custom policies for normal quizzes can be created below.
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

      {!loading && (
        <section className="rounded-xl border bg-card p-5 shadow-sm">
          <h2 className="text-lg font-semibold">Custom quiz scoring policies</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Teachers can attach these rules to a draft quiz before publishing it. Existing attempts keep their saved scoring snapshot.
          </p>
          {policies.length > 0 && (
            <ul className="mt-4 grid gap-2 sm:grid-cols-2">
              {policies.map((policy) => (
                <li key={policy.id} className="rounded-lg border px-3 py-2 text-sm">
                  <strong>{policy.name}</strong>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    Wrong answer: −{policy.rules.wrong_penalty ?? 0}{policy.rules.penalty_is_fraction ? " × marks" : " marks"}
                    {policy.rules.multi_mode === "mrm_partial" ? " · partial multi-select credit" : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={createPolicy} className="mt-4 grid gap-3 rounded-lg border border-dashed p-4 sm:grid-cols-2">
            <label className="text-sm font-medium">
              Policy name
              <input required maxLength={120} className={`${field} mt-1`} value={policyName} onChange={(e) => setPolicyName(e.target.value)} placeholder="Weekly test — negative marking" />
            </label>
            <label className="text-sm font-medium">
              Wrong-answer deduction
              <input required type="number" min="0" max="100" step="0.01" className={`${field} mt-1`} value={wrongPenalty} onChange={(e) => setWrongPenalty(e.target.value)} />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={fractionalPenalty} onChange={(e) => setFractionalPenalty(e.target.checked)} />
              Treat deduction as a fraction of question marks
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={partialCredit} onChange={(e) => setPartialCredit(e.target.checked)} />
              Give partial credit on multi-select questions
            </label>
            <button disabled={creating} className="w-fit rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">
              {creating ? "Creating…" : "Create policy"}
            </button>
          </form>
        </section>
      )}
    </div>
  );
}
