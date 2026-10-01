// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({
  getHandwrittenSubmissionQuota: vi.fn(),
  listStudentEvaluationPapers: vi.fn(),
  submitHandwrittenAnswer: vi.fn(),
}));

import * as api from "@/lib/api";
import { HandwrittenEvaluation } from "./handwritten-evaluation";

const listPapers = vi.mocked(api.listStudentEvaluationPapers);
const getQuota = vi.mocked(api.getHandwrittenSubmissionQuota);
const submitAnswer = vi.mocked(api.submitHandwrittenAnswer);

beforeEach(() => {
  listPapers.mockResolvedValue([{
    id: "paper-1",
    course_level_id: "level-1",
    subject_id: "subject-1",
    title: "Business Law Paper 2",
    total_marks: 100,
    subject_name: "Business Laws",
    course_name: "CA",
    level_name: "Foundation",
  }]);
  getQuota.mockResolvedValue({
    paper_id: "paper-1",
    completed_attempts: 0,
    attempt_limit: 2,
    remaining_attempts: 2,
    active: false,
  });
  submitAnswer.mockImplementation(async (_paperId, _file, onProgress) => {
    onProgress?.({ stage: "uploading", percent: 35 });
    onProgress?.({ stage: "complete", percent: 100 });
    return {
      id: "submission-1",
      paper_id: "paper-1",
      upload_intent_id: "intent-1",
      status: "queued",
      submitted_at: "2026-10-01T00:00:00Z",
      report_available: false,
      retrigger_count: 0,
    };
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("HandwrittenEvaluation upload", () => {
  it("shows the ExamApp upload checks and opens the live evaluation tracker", async () => {
    const user = userEvent.setup();
    render(<HandwrittenEvaluation />);
    await user.click(await screen.findByRole("button", { name: /Attempt This Paper/i }));

    const dialog = screen.getByRole("dialog", { name: /Business Law Paper 2/i });
    expect(within(dialog).getByText("Before you upload")).toBeTruthy();
    expect(within(dialog).getByText(/full left margin visible/)).toBeTruthy();
    expect(within(dialog).getByText(/combine them into one file/)).toBeTruthy();
    expect(await within(dialog).findByText(/2 of 2 completed attempts remaining/)).toBeTruthy();

    const file = new File(["answer"], "answers.pdf", { type: "application/pdf" });
    await user.upload(within(dialog).getByLabelText(/Choose answer script/i), file);
    await user.click(within(dialog).getByRole("button", { name: "Submit for Evaluation" }));

    expect(await within(dialog).findByText("Submitted successfully")).toBeTruthy();
    await waitFor(() => expect(push).toHaveBeenCalledWith(
      "/dashboard/student/handwritten-evaluation/submissions/submission-1",
    ), { timeout: 1500 });
  });
});
