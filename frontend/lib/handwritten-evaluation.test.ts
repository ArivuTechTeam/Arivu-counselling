import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/public-env", () => ({
  PUBLIC_ENV: { apiBaseUrl: "http://localhost:8000" },
}));
vi.mock("@/lib/supabase", () => ({
  createClient: () => ({
    auth: {
      getSession: async () => ({
        data: { session: { access_token: "student-token" } },
      }),
    },
  }),
}));
vi.mock("@/lib/safe-next", () => ({
  safeDashboardNext: (path: string) => path,
}));

import {
  getHandwrittenEvaluationReport,
  listStudentEvaluationSubmissions,
} from "./api";

describe("handwritten evaluation report API", () => {
  beforeEach(() => {
    vi.stubGlobal("window", { setTimeout, clearTimeout });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("reloads persisted submissions and fetches the completed report", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ submissions: [{
        id: "submission-1", paper_id: "paper-1", upload_intent_id: "intent-1",
        status: "evaluated", submitted_at: "2026-09-29T00:00:00Z",
        job_id: "job-1", job_status: "done", report_available: true,
      }] }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        submission_id: "submission-1", status: "completed",
        submission_date: "2026-09-29T00:00:00Z",
        evaluation_date: "2026-09-29T00:03:00Z",
        paper: { id: "paper-1", title: "Business Law", total_marks: 100 },
        total_score: 64, total_marks: 100, percentage: 64,
        overall_feedback: "Good work", strengths: ["Q1"], areas_to_improve: ["Q2"],
        requires_review: false, questions: [],
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listStudentEvaluationSubmissions()).resolves.toMatchObject([
      { id: "submission-1", job_status: "done" },
    ]);
    await expect(getHandwrittenEvaluationReport("submission-1")).resolves.toMatchObject({
      total_score: 64,
      paper: { title: "Business Law" },
    });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "http://localhost:8000/api/v1/handwritten-evaluations/submissions",
      "http://localhost:8000/api/v1/handwritten-evaluations/submissions/submission-1/report",
    ]);
  });
});
