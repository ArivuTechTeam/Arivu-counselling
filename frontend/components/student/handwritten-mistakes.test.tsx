// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvaluationPaper, HandwrittenMistake } from "@/lib/api";
import { renderWithSWR } from "@/lib/test-render";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getHandwrittenMistakes: vi.fn(),
  listStudentEvaluationPapers: vi.fn(),
}));
vi.mock("@/lib/public-env", () => ({ PUBLIC_ENV: { apiBaseUrl: "http://localhost:8000" } }));
vi.mock("@/lib/supabase", () => ({ createClient: () => ({}) }));

import * as api from "@/lib/api";
import { HandwrittenMistakes } from "./handwritten-mistakes";

const getMistakes = vi.mocked(api.getHandwrittenMistakes);
const getPapers = vi.mocked(api.listStudentEvaluationPapers);

function mistake(overrides: Partial<HandwrittenMistake>): HandwrittenMistake {
  return {
    id: "m1",
    evaluation_id: "e1",
    question_result_id: null,
    category: "step_loss",
    severity: "major",
    description: "Skipped the journal entry for depreciation",
    marks_lost: 2.5,
    suggestion: "Show every journal entry step",
    chapter_name: "Depreciation",
    criterion_key: "c1",
    signature: "a".repeat(64),
    is_recurring: false,
    created_at: "2026-09-01T00:00:00Z",
    subject_id: "s-law",
    submission_id: "sub-1",
    paper_title: "Law Mock Test 1",
    ...overrides,
  };
}

const PAPERS = [
  { id: "p1", subject_id: "s-law", subject_name: "Business Law", title: "Law 1" },
  { id: "p2", subject_id: "s-law", subject_name: "Business Law", title: "Law 2" },
  { id: "p3", subject_id: "s-acc", subject_name: "Accounting", title: "Acc 1" },
] as EvaluationPaper[];

const ALL = [
  mistake({ id: "m1", severity: "major", description: "Major slip" }),
  mistake({ id: "m2", severity: "minor", description: "Minor slip", category: "presentation" }),
];

beforeEach(() => {
  getPapers.mockResolvedValue(PAPERS);
  // Behave like the server: honour the filters it is given.
  getMistakes.mockImplementation(async (filters = {}) =>
    ALL.filter((item) => !filters.severity || item.severity === filters.severity),
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("HandwrittenMistakes", () => {
  it("shows an empty state when there are no mistakes", async () => {
    getMistakes.mockResolvedValue([]);
    renderWithSWR(<HandwrittenMistakes />);

    expect(await screen.findByText("No mistakes recorded yet")).toBeTruthy();
  });

  it("renders every field of a mistake", async () => {
    getMistakes.mockResolvedValue([mistake({ is_recurring: true })]);
    renderWithSWR(<HandwrittenMistakes />);

    const card = within(
      (await screen.findByText("Skipped the journal entry for depreciation")).closest("article")!,
    );
    expect(card.getByText("Major")).toBeTruthy();
    expect(card.getByText("Step loss")).toBeTruthy();
    expect(card.getByText("Recurring")).toBeTruthy();
    expect(card.getByText("−2.5 marks")).toBeTruthy();
    expect(card.getByText("Show every journal entry step")).toBeTruthy();
    expect(card.getByText("Chapter: Depreciation")).toBeTruthy();
  });

  it("shows which paper a mistake came from and links to that report", async () => {
    getMistakes.mockResolvedValue([mistake({})]);
    renderWithSWR(<HandwrittenMistakes />);

    const card = within((await screen.findByText(/Skipped the journal entry/)).closest("article")!);
    expect(card.getByText("From: Business Law · Law Mock Test 1")).toBeTruthy();
    expect(card.getByRole("link", { name: "View report" }).getAttribute("href")).toBe(
      "/dashboard/student/handwritten-evaluation/submissions/sub-1",
    );
  });

  it("shows the paper without a link when the submission is unknown", async () => {
    getMistakes.mockResolvedValue([mistake({ submission_id: null })]);
    renderWithSWR(<HandwrittenMistakes />);

    const card = within((await screen.findByText(/Skipped the journal entry/)).closest("article")!);
    expect(card.getByText("From: Business Law · Law Mock Test 1")).toBeTruthy();
    expect(card.queryByRole("link", { name: "View report" })).toBeNull();
  });

  it("omits the source line when the backend could not resolve it", async () => {
    getMistakes.mockResolvedValue([
      mistake({ subject_id: null, submission_id: null, paper_title: null }),
    ]);
    renderWithSWR(<HandwrittenMistakes />);

    const card = within((await screen.findByText(/Skipped the journal entry/)).closest("article")!);
    expect(card.queryByText(/^From:/)).toBeNull();
    expect(card.queryByRole("link")).toBeNull();
  });

  it("filters by severity", async () => {
    const user = userEvent.setup();
    renderWithSWR(<HandwrittenMistakes />);
    expect(await screen.findByText("Major slip")).toBeTruthy();
    expect(screen.getByText("Minor slip")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Major" }));

    await waitFor(() => expect(screen.queryByText("Minor slip")).toBeNull());
    expect(screen.getByText("Major slip")).toBeTruthy();
    expect(getMistakes).toHaveBeenLastCalledWith({ subjectId: undefined, severity: "major" });
  });

  it("lists each subject once and filters by it", async () => {
    const user = userEvent.setup();
    renderWithSWR(<HandwrittenMistakes />);
    await screen.findByText("Major slip");

    const select = await screen.findByLabelText("Filter by subject");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "All subjects",
      "Accounting",
      "Business Law",
    ]);

    await user.selectOptions(select, "s-acc");

    await waitFor(() =>
      expect(getMistakes).toHaveBeenLastCalledWith({ subjectId: "s-acc", severity: undefined }),
    );
  });

  it("explains an empty result when filters are active", async () => {
    const user = userEvent.setup();
    getMistakes.mockImplementation(async (filters = {}) =>
      filters.severity ? [] : ALL,
    );
    renderWithSWR(<HandwrittenMistakes />);
    await screen.findByText("Major slip");

    await user.click(screen.getByRole("button", { name: "Moderate" }));

    expect(await screen.findByText("No mistakes match these filters")).toBeTruthy();
  });

  // Isolation: the page only ever asks for its own data — no student id, ever.
  it("never asks for another student's data", async () => {
    const user = userEvent.setup();
    renderWithSWR(<HandwrittenMistakes />);
    await screen.findByText("Major slip");
    await user.click(screen.getByRole("button", { name: "Minor" }));
    await waitFor(() => expect(getMistakes).toHaveBeenCalledTimes(2));

    for (const [filters] of getMistakes.mock.calls) {
      expect(Object.keys(filters ?? {}).sort()).toEqual(["severity", "subjectId"]);
    }
  });

  it("shows only the error, not data, when the server refuses (403/404)", async () => {
    getMistakes.mockRejectedValue(new Error("Learning data not found"));
    renderWithSWR(<HandwrittenMistakes />);

    expect(await screen.findByText("Learning data not found")).toBeTruthy();
    expect(screen.queryByText("Major slip")).toBeNull();
  });
});
