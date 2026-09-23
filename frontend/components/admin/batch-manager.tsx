"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Batch,
  BatchMember,
  addBatchMember,
  createBatch,
  listBatchMembers,
  listEligibleBatchStudents,
  listBatches,
  removeBatchMember,
  updateBatch,
} from "@/lib/api";
import { useCourses } from "@/lib/staff-queries";

const solidBtn =
  "inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-bold text-primary-foreground transition hover:opacity-90 disabled:opacity-50";
const ghostBtn =
  "inline-flex items-center gap-1.5 rounded-lg border border-input px-3 py-2 text-sm font-semibold text-foreground transition hover:bg-secondary disabled:opacity-50";
const field =
  "h-11 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

export function BatchManager() {
  const { data: courses } = useCourses();
  const courseName = (id: string) =>
    (courses ?? []).find((c) => c.id === id)?.name ?? "—";
  const levelName = (courseId: string, levelId: string) =>
    (courses ?? []).find((c) => c.id === courseId)?.levels?.find((l) => l.id === levelId)?.name ?? "—";

  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // create form
  const [courseId, setCourseId] = useState("");
  const [courseLevelId, setCourseLevelId] = useState("");
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  // roster panel
  const [openBatch, setOpenBatch] = useState<Batch | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setBatches(await listBatches());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load batches.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!courseId || !courseLevelId || !name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await createBatch(courseId, courseLevelId, name.trim());
      setName("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create the batch.");
    } finally {
      setCreating(false);
    }
  }

  async function changeStatus(batch: Batch, status: "active" | "archived") {
    if (status === "archived" && !window.confirm(`Archive "${batch.name}"? Students won't be assignable to it.`)) return;
    try {
      await updateBatch(batch.id, { status });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update the batch.");
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Batches</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Group students into batches (e.g. &ldquo;CA Foundation 2026&rdquo;). Students pick their
          batch at signup; teachers assign quizzes to specific batches.
        </p>
      </div>

      <form
        onSubmit={handleCreate}
        className="flex flex-wrap items-end gap-3 rounded-2xl border bg-card p-4 shadow-sm"
      >
        <div className="flex min-w-[200px] flex-1 flex-col gap-1">
          <label className="text-xs font-semibold text-muted-foreground">Course</label>
          <select className={field} value={courseId} onChange={(e) => {
            setCourseId(e.target.value);
            setCourseLevelId("");
          }}>
            <option value="">Select a course…</option>
            {(courses ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <div className="flex min-w-[180px] flex-1 flex-col gap-1">
          <label className="text-xs font-semibold text-muted-foreground">Level</label>
          <select className={field} value={courseLevelId} onChange={(e) => setCourseLevelId(e.target.value)} disabled={!courseId}>
            <option value="">{courseId ? "Select a level…" : "Select a course first…"}</option>
            {((courses ?? []).find((c) => c.id === courseId)?.levels ?? []).map((level) => (
              <option key={level.id} value={level.id}>{level.name}</option>
            ))}
          </select>
        </div>
        <div className="flex min-w-[200px] flex-1 flex-col gap-1">
          <label className="text-xs font-semibold text-muted-foreground">Batch name</label>
          <input
            className={field}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. CA Foundation 2026"
          />
        </div>
        <button className={solidBtn} type="submit" disabled={creating || !courseId || !courseLevelId || !name.trim()}>
          {creating ? "Creating…" : "Create batch"}
        </button>
      </form>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading batches…</p>
      ) : batches.length === 0 ? (
        <p className="rounded-xl border border-dashed bg-card/60 p-6 text-center text-sm text-muted-foreground">
          No batches yet. Create one above.
        </p>
      ) : (
        <div className="grid gap-3">
          {batches.map((b) => (
            <div
              key={b.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-4 shadow-sm"
            >
              <div>
                <p className="font-semibold">
                  {b.name}
                  {b.status === "archived" && (
                    <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                      archived
                    </span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground">
                  {courseName(b.course_id)} · {levelName(b.course_id, b.course_level_id)}
                </p>
              </div>
              <div className="flex gap-2">
                <button className={ghostBtn} onClick={() => setOpenBatch(b)}>
                  View roster
                </button>
                <button
                  className={ghostBtn}
                  onClick={() => changeStatus(b, b.status === "archived" ? "active" : "archived")}
                >
                  {b.status === "archived" ? "Restore" : "Archive"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {openBatch && (
        <RosterDialog batch={openBatch} onClose={() => setOpenBatch(null)} />
      )}
    </div>
  );
}

function RosterDialog({ batch, onClose }: { batch: Batch; onClose: () => void }) {
  const [members, setMembers] = useState<BatchMember[] | null>(null);
  const [eligible, setEligible] = useState<{ id: string; full_name?: string | null }[]>([]);
  const [studentId, setStudentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [memberRows, eligibleRows] = await Promise.all([
        listBatchMembers(batch.id),
        listEligibleBatchStudents(batch.id),
      ]);
      setMembers(memberRows);
      setEligible(eligibleRows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load the roster.");
    }
  }, [batch.id]);
  useEffect(() => {
    void load();
  }, [load]);

  async function remove(m: BatchMember) {
    if (!window.confirm(`Remove ${m.full_name ?? "this student"} from ${batch.name}?`)) return;
    try {
      await removeBatchMember(batch.id, m.profile_id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove the member.");
    }
  }

  async function add() {
    if (!studentId) return;
    setBusy(true);
    setError(null);
    try {
      await addBatchMember(batch.id, studentId);
      setStudentId("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add the student.");
    } finally {
      setBusy(false);
    }
  }

  const active = (members ?? []).filter((m) => m.active);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-2xl border bg-card p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{batch.name} — roster</h2>
          <button className={ghostBtn} onClick={onClose}>Close</button>
        </div>
        {error && <p className="mb-2 text-sm text-destructive">{error}</p>}
        {batch.status === "active" && (
          <div className="mb-4 flex gap-2">
            <select className={field} value={studentId} onChange={(e) => setStudentId(e.target.value)}>
              <option value="">Add an enrolled student…</option>
              {eligible
                .filter((student) => !active.some((member) => member.profile_id === student.id))
                .map((student) => (
                  <option key={student.id} value={student.id}>
                    {student.full_name ?? student.id}
                  </option>
                ))}
            </select>
            <button className={solidBtn} type="button" disabled={busy || !studentId} onClick={add}>
              Add
            </button>
          </div>
        )}
        {members === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : active.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No active members yet. Students appear here after they select this batch at signup.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {active.map((m) => (
              <li key={m.id} className="flex items-center justify-between py-2.5">
                <span className="text-sm">{m.full_name ?? m.profile_id}</span>
                <button className={ghostBtn} onClick={() => remove(m)}>Remove</button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
