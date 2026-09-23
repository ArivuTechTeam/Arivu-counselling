"use client";

import { useCallback, useEffect, useState } from "react";

import {
  CoursePaperProfile,
  PaperProfileFields,
  listPaperProfiles,
  setPaperProfile,
} from "@/lib/api";

const field =
  "h-11 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-50";

const EMPTY: PaperProfileFields = {
  exam_body: "",
  level: "",
  paper: "",
  assessment_year: "",
  framework: "",
};

const FIELDS: { key: keyof PaperProfileFields; label: string; placeholder: string }[] = [
  { key: "exam_body", label: "Exam body", placeholder: "ICAI, ICMAI, ACCA…" },
  { key: "paper", label: "Paper", placeholder: "Paper 4 — Business Economics" },
  { key: "assessment_year", label: "Assessment year", placeholder: "2025-26" },
  { key: "framework", label: "Framework", placeholder: "Indian GAAP, Ind AS, IFRS…" },
];

function toForm(profile: PaperProfileFields | null): PaperProfileFields {
  if (!profile) return { ...EMPTY };
  return {
    exam_body: profile.exam_body ?? "",
    level: profile.level ?? "",
    paper: profile.paper ?? "",
    assessment_year: profile.assessment_year ?? "",
    framework: profile.framework ?? "",
  };
}

export function PaperProfilesManager() {
  const [rows, setRows] = useState<CoursePaperProfile[]>([]);
  const [forms, setForms] = useState<Record<string, PaperProfileFields>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await listPaperProfiles();
      setRows(data);
      setForms(Object.fromEntries(data.map((r) => [r.course_level_id, toForm(r.profile)])));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load paper profiles.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  function edit(courseLevelId: string, key: keyof PaperProfileFields, value: string) {
    setForms((f) => ({ ...f, [courseLevelId]: { ...f[courseLevelId], [key]: value } }));
  }

  async function save(courseLevelId: string) {
    setSaving(courseLevelId);
    setError(null);
    setSavedAt(null);
    try {
      const res = await setPaperProfile(courseLevelId, forms[courseLevelId] ?? EMPTY);
      setForms((f) => ({ ...f, [courseLevelId]: toForm(res.profile) }));
      setRows((rs) =>
        rs.map((r) => (r.course_level_id === courseLevelId ? { ...r, profile: res.profile } : r)),
      );
      setSavedAt(courseLevelId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the paper profile.");
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Paper profiles</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Tell the AI which exam each course level is for — the{" "}
          <strong>assessment year, jurisdiction and accounting framework</strong>. When the
          commerce pack is on, generated questions pin year- and rule-specific figures to
          exactly these, so nothing goes stale. The level comes from your academic
          hierarchy; leave the other fields blank to keep today&apos;s behaviour.
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
        <div className="grid gap-4">
          {rows.map((row) => {
            const form = forms[row.course_level_id] ?? EMPTY;
            return (
              <div key={row.course_level_id} className="rounded-xl border bg-card p-4 shadow-sm">
                <p className="mb-3 font-semibold">{row.course_name} · {row.level_name}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  {FIELDS.map((f) => (
                    <label key={f.key} className="flex flex-col gap-1 text-xs text-muted-foreground">
                      {f.label}
                      <input
                        className={field}
                        value={form[f.key] ?? ""}
                        placeholder={f.placeholder}
                        disabled={saving === row.course_level_id}
                        onChange={(e) => edit(row.course_level_id, f.key, e.target.value)}
                      />
                    </label>
                  ))}
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void save(row.course_level_id)}
                    disabled={saving === row.course_level_id}
                    className="inline-flex h-10 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                  >
                    {saving === row.course_level_id ? "Saving…" : "Save"}
                  </button>
                  {savedAt === row.course_level_id && (
                    <span className="text-xs text-muted-foreground">Saved.</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
