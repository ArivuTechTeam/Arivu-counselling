// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvaluationPaper, HandwrittenRevisionItem } from "@/lib/api";
import { renderWithSWR } from "@/lib/test-render";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getHandwrittenRevisionItems: vi.fn(),
  listStudentEvaluationPapers: vi.fn(),
}));
vi.mock("@/lib/public-env", () => ({ PUBLIC_ENV: { apiBaseUrl: "http://localhost:8000" } }));
vi.mock("@/lib/supabase", () => ({ createClient: () => ({}) }));

import * as api from "@/lib/api";
import { HandwrittenRevision } from "./handwritten-revision";

const getItems = vi.mocked(api.getHandwrittenRevisionItems);
const getPapers = vi.mocked(api.listStudentEvaluationPapers);

function item(overrides: Partial<HandwrittenRevisionItem>): HandwrittenRevisionItem {
  return {
    id: "r1",
    subject_id: "s-law",
    chapter: "Contracts",
    title: "Offer and acceptance",
    description: "Missed the communication rule",
    priority: "high",
    is_resolved: false,
    occurrence_count: 3,
    marks_at_risk: 6,
    source_count: 2,
    resolution_source: "",
    resolved_at: null,
    last_seen_at: "2026-09-01T00:00:00Z",
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

const PAPERS = [
  { id: "p1", subject_id: "s-law", subject_name: "Business Law", title: "Law 1" },
  { id: "p2", subject_id: "s-acc", subject_name: "Accounting", title: "Acc 1" },
] as EvaluationPaper[];

const ALL = [
  item({ id: "low", title: "Low one", priority: "low", marks_at_risk: 9 }),
  item({ id: "high", title: "High one", priority: "high", marks_at_risk: 2 }),
  item({ id: "med", title: "Medium one", priority: "medium", marks_at_risk: 4 }),
  item({
    id: "done",
    title: "Done one",
    priority: "medium",
    is_resolved: true,
    resolution_source: "improved",
    marks_at_risk: 0,
  }),
];

beforeEach(() => {
  getPapers.mockResolvedValue(PAPERS);
  // Behave like the server: honour the resolved filter.
  getItems.mockImplementation(async (filters = {}) =>
    ALL.filter((row) => filters.resolved === undefined || row.is_resolved === filters.resolved),
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("HandwrittenRevision", () => {
  it("shows an empty state when there is nothing to revise", async () => {
    getItems.mockResolvedValue([]);
    renderWithSWR(<HandwrittenRevision />);

    expect(await screen.findByText("Nothing to revise right now")).toBeTruthy();
  });

  it("renders every field of an item", async () => {
    getItems.mockResolvedValue([item({})]);
    renderWithSWR(<HandwrittenRevision />);

    const card = within((await screen.findByText("Offer and acceptance")).closest("article")!);
    expect(card.getByText("High priority")).toBeTruthy();
    expect(card.getByText("Unresolved")).toBeTruthy();
    expect(card.getByText("6 marks at risk")).toBeTruthy();
    expect(card.getByText("Business Law · Contracts")).toBeTruthy();
    expect(card.getByText("Missed the communication rule")).toBeTruthy();
    expect(card.getByText(/Seen 3 times across 2 answer scripts/)).toBeTruthy();
  });

  it("gives each priority its own label", async () => {
    getItems.mockResolvedValue(ALL.slice(0, 3));
    renderWithSWR(<HandwrittenRevision />);
    await screen.findByText("High one");

    expect(screen.getByText("High priority")).toBeTruthy();
    expect(screen.getByText("Medium priority")).toBeTruthy();
    expect(screen.getByText("Low priority")).toBeTruthy();
  });

  it("lists the most urgent items first", async () => {
    renderWithSWR(<HandwrittenRevision />);
    await screen.findByText("High one");

    const titles = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(titles).toEqual(["High one", "Medium one", "Low one"]);
  });

  it("starts on unresolved and switches to resolved", async () => {
    const user = userEvent.setup();
    renderWithSWR(<HandwrittenRevision />);
    await screen.findByText("High one");
    expect(getItems).toHaveBeenLastCalledWith({ subjectId: undefined, resolved: false });
    expect(screen.queryByText("Done one")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Resolved" }));

    const done = await screen.findByText("Done one");
    expect(screen.queryByText("High one")).toBeNull();
    expect(within(done.closest("article")!).getByText("Resolved · improved")).toBeTruthy();
    expect(getItems).toHaveBeenLastCalledWith({ subjectId: undefined, resolved: true });
  });

  it("shows both states under All", async () => {
    const user = userEvent.setup();
    renderWithSWR(<HandwrittenRevision />);
    await screen.findByText("High one");

    await user.click(screen.getByRole("button", { name: "All" }));

    expect(await screen.findByText("Done one")).toBeTruthy();
    expect(screen.getByText("High one")).toBeTruthy();
    expect(getItems).toHaveBeenLastCalledWith({ subjectId: undefined, resolved: undefined });
  });

  it("filters by subject", async () => {
    const user = userEvent.setup();
    renderWithSWR(<HandwrittenRevision />);
    await screen.findByText("High one");

    await user.selectOptions(await screen.findByLabelText("Filter by subject"), "s-acc");

    await waitFor(() =>
      expect(getItems).toHaveBeenLastCalledWith({ subjectId: "s-acc", resolved: false }),
    );
  });

  it("explains an empty result when filters are active", async () => {
    const user = userEvent.setup();
    getItems.mockImplementation(async (filters = {}) => (filters.resolved ? [] : ALL));
    renderWithSWR(<HandwrittenRevision />);
    await screen.findByText("High one");

    await user.click(screen.getByRole("button", { name: "Resolved" }));

    expect(await screen.findByText("No revision items match these filters")).toBeTruthy();
  });

  // Isolation: the page only ever asks for its own data — no student id, ever.
  it("never asks for another student's data", async () => {
    const user = userEvent.setup();
    renderWithSWR(<HandwrittenRevision />);
    await screen.findByText("High one");
    await user.click(screen.getByRole("button", { name: "All" }));
    await waitFor(() => expect(getItems).toHaveBeenCalledTimes(2));

    for (const [filters] of getItems.mock.calls) {
      expect(Object.keys(filters ?? {}).sort()).toEqual(["resolved", "subjectId"]);
    }
  });

  it("shows only the error, not data, when the server refuses (403/404)", async () => {
    getItems.mockRejectedValue(new Error("Learning data not found"));
    renderWithSWR(<HandwrittenRevision />);

    expect(await screen.findByText("Learning data not found")).toBeTruthy();
    expect(screen.queryByText("High one")).toBeNull();
  });
});
