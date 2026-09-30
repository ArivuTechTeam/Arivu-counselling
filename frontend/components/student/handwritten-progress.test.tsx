// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvaluationPaper, HandwrittenAnalytics } from "@/lib/api";
import { renderWithSWR } from "@/lib/test-render";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getHandwrittenAnalytics: vi.fn(),
  getHandwrittenWeakAreas: vi.fn(),
  listStudentEvaluationPapers: vi.fn(),
}));
vi.mock("@/lib/public-env", () => ({ PUBLIC_ENV: { apiBaseUrl: "http://localhost:8000" } }));
vi.mock("@/lib/supabase", () => ({ createClient: () => ({}) }));

import * as api from "@/lib/api";
import { HandwrittenProgress } from "./handwritten-progress";

const getAnalytics = vi.mocked(api.getHandwrittenAnalytics);
const getWeakAreas = vi.mocked(api.getHandwrittenWeakAreas);
const getPapers = vi.mocked(api.listStudentEvaluationPapers);

function analytics(overrides: Partial<HandwrittenAnalytics>): HandwrittenAnalytics {
  return {
    id: "a1",
    subject_id: "s-law",
    total_attempts: 3,
    avg_percentage: 62.5,
    best_percentage: 71,
    latest_percentage: 68,
    score_history: [
      { evaluation_id: "e1", percentage: 50, date: "2026-08-01" },
      { evaluation_id: "e2", percentage: 65, date: "2026-08-15" },
      { evaluation_id: "e3", percentage: 68, date: "2026-09-01" },
    ],
    current_level: "advanced",
    improvement_rate: 9,
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

const PAPERS = [
  { id: "p1", subject_id: "s-law", subject_name: "Business Law", title: "Law 1" },
  { id: "p2", subject_id: "s-acc", subject_name: "Accounting", title: "Acc 1" },
] as EvaluationPaper[];

beforeEach(() => {
  getPapers.mockResolvedValue(PAPERS);
  getAnalytics.mockImplementation(async (subjectId) =>
    subjectId === "s-law" ? analytics({}) : null,
  );
  getWeakAreas.mockResolvedValue({ weak_chapters: [], mistake_patterns: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("HandwrittenProgress", () => {
  it("shows an empty state when the student has no subjects", async () => {
    getPapers.mockResolvedValue([]);
    renderWithSWR(<HandwrittenProgress />);

    expect(await screen.findByText("No progress to show yet")).toBeTruthy();
    expect(getAnalytics).not.toHaveBeenCalled();
  });

  it("shows a per-subject empty message when a subject has no analytics yet", async () => {
    renderWithSWR(<HandwrittenProgress />);

    const accounting = within(await screen.findByRole("region", { name: "Accounting progress" }));
    expect(await accounting.findByText(/No evaluated answer scripts/)).toBeTruthy();
  });

  it("renders attempts, scores, level, trend and recent attempts", async () => {
    renderWithSWR(<HandwrittenProgress />);

    const law = within(await screen.findByRole("region", { name: "Business Law progress" }));
    expect(await law.findByText("Advanced")).toBeTruthy();
    expect(law.getByRole("img", { name: "Level 4 of 5" })).toBeTruthy();
    expect(law.getByText("Attempts").nextSibling?.textContent).toBe("3");
    expect(law.getByText("Average").nextSibling?.textContent).toBe("62.5%");
    expect(law.getByText("Best").nextSibling?.textContent).toBe("71%");
    expect(law.getByText("Latest").nextSibling?.textContent).toBe("68%");
    expect(law.getByText(/\+9 pts per attempt/)).toBeTruthy();
    expect(law.getByRole("img", { name: "Score trend" })).toBeTruthy();

    const recent = within(law.getByRole("list", { name: "Recent attempts" }));
    expect(recent.getAllByRole("listitem").map((row) => row.textContent)).toEqual([
      "2026-09-0168%",
      "2026-08-1565%",
      "2026-08-0150%",
    ]);
  });

  it("marks a falling score as a decline", async () => {
    getAnalytics.mockResolvedValue(analytics({ improvement_rate: -4, current_level: "beginner" }));
    renderWithSWR(<HandwrittenProgress />);

    expect((await screen.findAllByText(/▼ -4 pts per attempt/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Beginner").length).toBeGreaterThan(0);
  });

  it("ignores analytics fields that were deliberately left out", async () => {
    getAnalytics.mockResolvedValue({
      ...analytics({}),
      streak_count: 7,
      weak_chapters: [{ chapter: "SECRET-CHAPTER" }],
      top_mistake_categories: ["SECRET-CATEGORY"],
    } as HandwrittenAnalytics);
    renderWithSWR(<HandwrittenProgress />);
    await screen.findAllByText("Advanced");

    expect(screen.queryByText(/SECRET/)).toBeNull();
    expect(screen.queryByText(/streak/i)).toBeNull();
  });

  it("shows weak areas from the backend's live computation", async () => {
    getWeakAreas.mockResolvedValue({
      weak_chapters: [{
        subject_id: "s-law", chapter: "Contracts", title: "Offer and acceptance",
        marks_at_risk: 6, source_count: 2, priority: "high", last_seen_at: "2026-09-01",
      }],
      mistake_patterns: [{ category: "step_loss", count: 4, total_marks_lost: 7.5 }],
    });
    renderWithSWR(<HandwrittenProgress />);

    const panel = within(await screen.findByRole("region", { name: "Weak areas" }));
    expect(await panel.findByText("Offer and acceptance")).toBeTruthy();
    expect(panel.getByText("Business Law · Contracts")).toBeTruthy();
    expect(panel.getByText("6 marks at risk")).toBeTruthy();
    expect(panel.getByText("High priority")).toBeTruthy();
    expect(panel.getByText("Step loss")).toBeTruthy();
    expect(panel.getByText(/4 mistakes/)).toBeTruthy();
  });

  it("says so when nothing is costing the student marks", async () => {
    renderWithSWR(<HandwrittenProgress />);

    expect(await screen.findByText(/No weak areas found/)).toBeTruthy();
  });

  // Isolation: only subjects from the student's own papers are ever requested,
  // and the weak-areas request carries no student or other-subject scope.
  it("only requests its own subjects and never a student id", async () => {
    renderWithSWR(<HandwrittenProgress />);
    await screen.findByText("No weak areas found — nothing is costing you marks.");

    expect(getAnalytics.mock.calls.map(([subjectId]) => subjectId).sort()).toEqual([
      "s-acc",
      "s-law",
    ]);
    expect(getWeakAreas).toHaveBeenCalledWith(undefined);
  });

  it("shows only the error, not data, when analytics is refused (403)", async () => {
    getAnalytics.mockRejectedValue(new Error("Students can view only their own learning data"));
    renderWithSWR(<HandwrittenProgress />);

    expect((await screen.findAllByText("Students can view only their own learning data")).length)
      .toBeGreaterThan(0);
    expect(screen.queryByText("Advanced")).toBeNull();
  });
});
