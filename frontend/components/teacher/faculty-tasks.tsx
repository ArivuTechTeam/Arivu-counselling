"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { cancelFacultyJob, FacultyJob, listFacultyJobs } from "@/lib/api";

export function FacultyTasks() {
  const [jobs, setJobs] = useState<FacultyJob[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let loading = false;
    async function refresh() {
      if (loading || stopped) return;
      clearTimeout(timer);
      loading = true;
      try {
        const response = await listFacultyJobs();
        if (!stopped) {
          setEnabled(response.enabled);
          setJobs(response.jobs);
          setError(null);
        }
      } catch {
        if (!stopped) setError("Task status is temporarily unavailable. A connection error does not cancel queued work.");
      }
      loading = false;
      if (!stopped) timer = setTimeout(refresh, 5000);
    }
    window.addEventListener("faculty-job-queued", refresh);
    void refresh();
    return () => { stopped = true; clearTimeout(timer); window.removeEventListener("faculty-job-queued", refresh); };
  }, []);
  if ((!enabled || jobs.length === 0) && !error) return null;
  async function cancel(id: string) {
    setCancelling(id);
    try {
      const updated = await cancelFacultyJob(id);
      setJobs((current) => current.map((job) => job.id === id ? updated : job));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Cancellation could not be confirmed.");
    } finally { setCancelling(null); }
  }
  return (
    <section className="mb-6 rounded-xl border bg-card p-4" aria-label="Recent background tasks">
      <h2 className="font-semibold">Recent tasks</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Once generation or import is queued here, you can leave or refresh this page.
        Return here to open the quiz when it is ready. Topic analysis still uses its existing workflow.
      </p>
      {error && <p role="alert" className="mt-2 text-sm text-destructive">{error}</p>}
      {!jobs.length && <p className="mt-2 text-sm text-muted-foreground">No background tasks yet.</p>}
      <ul className="mt-3 max-h-64 space-y-3 overflow-y-auto">
        {jobs.map((job) => (
          <li key={job.id} className="flex flex-wrap items-center justify-between gap-2 border-t pt-2 text-sm">
            <div>
              <p>{job.kind === "extraction" ? "Import" : "Quiz generation"} · {new Date(job.created_at).toLocaleString()}</p>
              <p className="capitalize text-muted-foreground">{job.phase === "retrying" ? "Retry queued" : job.phase === "saving" ? "Saving draft" : job.status}</p>
              {job.error_message && <p className="text-muted-foreground">{job.error_message}</p>}
            </div>
            {job.status === "completed" && job.result?.quiz_set_id && (
              <Link className="font-medium text-primary underline" href={job.result.quiz_status === "published"
                ? `/dashboard/teacher/published-quizzes/${job.result.quiz_set_id}`
                : `/dashboard/teacher/review/${job.result.quiz_set_id}`}>Open quiz</Link>
            )}
            {["queued", "running"].includes(job.status) && (
              <Button size="sm" variant="outline" disabled={cancelling === job.id} onClick={() => cancel(job.id)}>
                {cancelling === job.id ? "Cancelling…" : "Cancel"}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
