// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  getEvaluationSubmission: vi.fn(),
  getHandwrittenEvaluationReport: vi.fn(),
}));

import * as api from "@/lib/api";
import { HandwrittenReport } from "./handwritten-report";

const getSubmission = vi.mocked(api.getEvaluationSubmission);
const getReport = vi.mocked(api.getHandwrittenEvaluationReport);

beforeEach(() => {
  getSubmission.mockResolvedValue({
    id: "submission-1",
    paper_id: "paper-1",
    upload_intent_id: "intent-1",
    status: "processing_stage1",
    job_status: "processing",
    submitted_at: new Date().toISOString(),
    report_available: false,
    paper_title: "Business Law Paper 2",
    retrigger_count: 0,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("HandwrittenReport evaluation tracker", () => {
  it("shows the active ExamApp-style evaluation screen until the report is ready", async () => {
    render(<HandwrittenReport submissionId="submission-1" />);

    expect(await screen.findByText("AI Evaluation In Progress")).toBeTruthy();
    expect(screen.getByText("AI examiner activated")).toBeTruthy();
    expect(screen.getByText(/Reading and organizing your handwritten answers/)).toBeTruthy();
    expect(screen.getByText(/refreshes automatically/)).toBeTruthy();
    expect(getReport).not.toHaveBeenCalled();
  });
});
