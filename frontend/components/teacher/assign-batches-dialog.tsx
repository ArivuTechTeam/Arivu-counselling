"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Batch,
  QuizAssignment,
  assignToBatches,
  listAssignments,
  listEligibleBatches,
  withdrawAssignment,
} from "@/lib/api";

const ghostBtn =
  "inline-flex items-center gap-1.5 rounded-lg border border-input px-3 py-2 text-sm font-semibold text-foreground transition hover:bg-secondary disabled:opacity-50";
const solidBtn =
  "inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-bold text-primary-foreground transition hover:opacity-90 disabled:opacity-50";
const field =
  "h-10 flex-1 rounded-lg border border-input bg-background px-3 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

export function AssignBatchesDialog({
  quizSetId,
  quizTitle,
  onClose,
}: {
  quizSetId: string;
  quizTitle: string;
  onClose: () => void;
}) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [assignments, setAssignments] = useState<QuizAssignment[]>([]);
  const [pick, setPick] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [b, a] = await Promise.all([listEligibleBatches(quizSetId), listAssignments(quizSetId)]);
      setBatches(b);
      setAssignments(a.filter((x) => x.status === "active"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load batches.");
    } finally {
      setLoading(false);
    }
  }, [quizSetId]);
  useEffect(() => {
    void load();
  }, [load]);

  const assignedIds = new Set(assignments.map((a) => a.batch_id));
  const batchName = (id: string) => batches.find((b) => b.id === id)?.name ?? id;
  const available = batches.filter((b) => !assignedIds.has(b.id));

  async function assign() {
    if (!pick) return;
    setBusy(true);
    setError(null);
    try {
      await assignToBatches(quizSetId, [pick]);
      setPick("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't assign to that batch.");
    } finally {
      setBusy(false);
    }
  }

  async function withdraw(batchId: string) {
    setBusy(true);
    setError(null);
    try {
      await withdrawAssignment(quizSetId, batchId);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't withdraw the assignment.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl border bg-card p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Assign to batches</h2>
          <button className={ghostBtn} onClick={onClose}>Close</button>
        </div>
        <p className="mb-4 truncate text-sm text-muted-foreground">{quizTitle}</p>

        {error && <p className="mb-3 text-sm text-destructive">{error}</p>}

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <>
            <div className="mb-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Currently assigned
              </p>
              {assignments.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Not assigned to any batch yet — only assigned batches can see this quiz.
                </p>
              ) : (
                <ul className="divide-y divide-border rounded-lg border">
                  {assignments.map((a) => (
                    <li key={a.id} className="flex items-center justify-between px-3 py-2">
                      <span className="text-sm">{batchName(a.batch_id)}</span>
                      <button className={ghostBtn} disabled={busy} onClick={() => withdraw(a.batch_id)}>
                        Withdraw
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Add a batch
            </p>
            {available.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {batches.length === 0
                  ? "No batches exist yet. Ask an admin to create one."
                  : "All available batches are already assigned."}
              </p>
            ) : (
              <div className="flex items-center gap-2">
                <select className={field} value={pick} onChange={(e) => setPick(e.target.value)}>
                  <option value="">Select a batch…</option>
                  {available.map((b) => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </select>
                <button className={solidBtn} disabled={busy || !pick} onClick={assign}>
                  {busy ? "Assigning…" : "Assign"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
