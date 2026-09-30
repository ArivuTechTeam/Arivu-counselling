"use client";

import { useCallback, useEffect, useState } from "react";

import {
  CoursePaperProfile,
  PaperFormatConfig,
  PaperProfileFields,
  listPaperProfiles,
  setPaperProfile,
} from "@/lib/api";

const field =
  "h-11 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-50";

const EMPTY_FORMAT: PaperFormatConfig = {
  sections: [],
  instructions: [],
  numbering_style: "numeric",
  duration_minutes: null,
  currency_symbol: null,
  locale: null,
};

const EMPTY: PaperProfileFields = {
  exam_body: "",
  level: "",
  paper: "",
  assessment_year: "",
  framework: "",
  format_config: EMPTY_FORMAT,
};

type TextProfileField = Exclude<keyof PaperProfileFields, "format_config">;
const FIELDS: { key: TextProfileField; label: string; placeholder: string }[] = [
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
    format_config: {
      ...EMPTY_FORMAT,
      ...(profile.format_config ?? {}),
      sections: profile.format_config?.sections ?? [],
      instructions: profile.format_config?.instructions ?? [],
    },
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

  function edit(courseLevelId: string, key: TextProfileField, value: string) {
    setForms((f) => ({ ...f, [courseLevelId]: { ...f[courseLevelId], [key]: value } }));
  }

  function editFormat(courseLevelId: string, change: Partial<PaperFormatConfig>) {
    setForms((current) => {
      const existing = current[courseLevelId] ?? toForm(null);
      return {
        ...current,
        [courseLevelId]: {
          ...existing,
          format_config: { ...EMPTY_FORMAT, ...existing.format_config, ...change },
        },
      };
    });
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
                <div className="mt-4 border-t pt-4">
                  <p className="font-medium">Exam-paper format</p>
                  <p className="mb-3 text-xs text-muted-foreground">
                    Used by generated question papers; values are specific to this course level.
                  </p>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                      Duration (minutes)
                      <input
                        className={field}
                        type="number"
                        min={1}
                        max={1440}
                        value={form.format_config?.duration_minutes ?? ""}
                        onChange={(event) => editFormat(row.course_level_id, {
                          duration_minutes: event.target.value ? Number(event.target.value) : null,
                        })}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                      Numbering
                      <select
                        className={field}
                        value={form.format_config?.numbering_style ?? "numeric"}
                        onChange={(event) => editFormat(row.course_level_id, {
                          numbering_style: event.target.value as PaperFormatConfig["numbering_style"],
                        })}
                      >
                        <option value="numeric">1, 2, 3</option>
                        <option value="q_numeric">Q1, Q2, Q3</option>
                        <option value="roman">I, II, III</option>
                      </select>
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                      Currency symbol
                      <input
                        className={field}
                        value={form.format_config?.currency_symbol ?? ""}
                        placeholder="₹, $, £…"
                        onChange={(event) => editFormat(row.course_level_id, { currency_symbol: event.target.value || null })}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                      Locale
                      <input
                        className={field}
                        value={form.format_config?.locale ?? ""}
                        placeholder="en-IN"
                        onChange={(event) => editFormat(row.course_level_id, { locale: event.target.value || null })}
                      />
                    </label>
                  </div>
                  <label className="mt-3 flex flex-col gap-1 text-xs text-muted-foreground">
                    Instructions (one per line)
                    <textarea
                      className="min-h-24 w-full rounded-lg border border-input bg-background p-3 text-sm text-foreground"
                      value={(form.format_config?.instructions ?? []).join("\n")}
                      onChange={(event) => editFormat(row.course_level_id, {
                        instructions: event.target.value.split("\n").map((line) => line.trim()).filter(Boolean),
                      })}
                    />
                  </label>
                  <div className="mt-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-medium text-muted-foreground">Sections</p>
                      <button
                        type="button"
                        className="text-xs font-medium text-primary"
                        onClick={() => editFormat(row.course_level_id, {
                          sections: [...(form.format_config?.sections ?? []), { name: "New section", count: 1 }],
                        })}
                      >
                        + Add section
                      </button>
                    </div>
                    {(form.format_config?.sections ?? []).map((section, index) => (
                      <div key={index} className="grid gap-2 rounded-lg border p-3 sm:grid-cols-[2fr_1.5fr_0.7fr_0.8fr_0.8fr_auto]">
                        <input className={field} aria-label="Section name" value={section.name} onChange={(event) => {
                          const sections = [...(form.format_config?.sections ?? [])];
                          sections[index] = { ...section, name: event.target.value };
                          editFormat(row.course_level_id, { sections });
                        }} />
                        <input className={field} aria-label="Question type" placeholder="mcq_single" value={section.question_type ?? ""} onChange={(event) => {
                          const sections = [...(form.format_config?.sections ?? [])];
                          sections[index] = { ...section, question_type: event.target.value || null };
                          editFormat(row.course_level_id, { sections });
                        }} />
                        <input className={field} aria-label="Question count" type="number" min={1} max={50} value={section.count} onChange={(event) => {
                          const sections = [...(form.format_config?.sections ?? [])];
                          sections[index] = { ...section, count: Number(event.target.value) };
                          editFormat(row.course_level_id, { sections });
                        }} />
                        <input className={field} aria-label="Minimum marks" type="number" min={0.5} step={0.5} placeholder="Min marks" value={section.min_marks ?? ""} onChange={(event) => {
                          const sections = [...(form.format_config?.sections ?? [])];
                          sections[index] = { ...section, min_marks: event.target.value ? Number(event.target.value) : null };
                          editFormat(row.course_level_id, { sections });
                        }} />
                        <input className={field} aria-label="Maximum marks" type="number" min={0.5} step={0.5} placeholder="Max marks" value={section.max_marks ?? ""} onChange={(event) => {
                          const sections = [...(form.format_config?.sections ?? [])];
                          sections[index] = { ...section, max_marks: event.target.value ? Number(event.target.value) : null };
                          editFormat(row.course_level_id, { sections });
                        }} />
                        <button type="button" className="px-2 text-xs text-destructive" onClick={() => editFormat(row.course_level_id, {
                          sections: (form.format_config?.sections ?? []).filter((_, itemIndex) => itemIndex !== index),
                        })}>Remove</button>
                      </div>
                    ))}
                  </div>
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
