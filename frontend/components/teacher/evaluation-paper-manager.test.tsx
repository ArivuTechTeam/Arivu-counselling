// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Course, EvaluationPaper } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  createEvaluationPaper: vi.fn(),
  deleteEvaluationPaper: vi.fn(),
  getEvaluationPaper: vi.fn(),
  getEvaluationSubmissionAnswerScriptUrl: vi.fn(),
  listCourses: vi.fn(),
  listEvaluationPaperSubmissions: vi.fn(),
  listEvaluationPapers: vi.fn(),
  updateEvaluationPaper: vi.fn(),
}));

import * as api from "@/lib/api";
import { EvaluationPaperManager } from "./evaluation-paper-manager";

const listCourses = vi.mocked(api.listCourses);
const listPapers = vi.mocked(api.listEvaluationPapers);
const getPaper = vi.mocked(api.getEvaluationPaper);
const updatePaper = vi.mocked(api.updateEvaluationPaper);
const listPaperSubmissions = vi.mocked(api.listEvaluationPaperSubmissions);

const COURSES: Course[] = [{
  id: "course-1",
  name: "CA",
  levels: [{ id: "level-1", name: "Foundation" }],
  subjects: [{ id: "subject-1", name: "Business Laws", course_level_id: "level-1" }],
}];

const PAPER: EvaluationPaper = {
  id: "paper-1",
  course_level_id: "level-1",
  subject_id: "subject-1",
  subject_name: "Business Laws",
  course_name: "CA",
  level_name: "Foundation",
  title: "Business law 100%",
  total_marks: 100,
  mcq_marks: 30,
  rubric_status: "ready",
  is_active: true,
  has_suggested_answer: true,
  submission_count: 11,
  created_at: "2026-08-10T00:00:00Z",
};

const DETAIL: EvaluationPaper = {
  ...PAPER,
  question_paper_url: "https://files.example/question.pdf",
  suggested_answer_url: "https://files.example/answers.pdf",
  question_paper_text: "Question No. 1 is compulsory.\nAnswer any four questions.",
  suggested_answer_text: "1(a) The contract is enforceable when...",
  rubric_source: "official",
  structured_qa: [{
    question_ref: "1(a)",
    question_text: "Explain the legal position.",
    suggested_answer: "Apply the relevant provision.",
    total_marks: 7,
    criteria: [{ criterion_id: "c1", description: "States the provision", marks: 2 }],
  }],
};

beforeEach(() => {
  listCourses.mockResolvedValue(COURSES);
  listPapers.mockResolvedValue([PAPER]);
  getPaper.mockResolvedValue(DETAIL);
  updatePaper.mockImplementation(async (_id, input) => ({ ...DETAIL, ...input }));
  listPaperSubmissions.mockResolvedValue([{
    id: "submission-1",
    paper_id: "paper-1",
    upload_intent_id: "intent-1",
    status: "evaluated",
    submitted_at: "2026-08-12T10:00:00Z",
    job_status: "done",
    report_available: true,
    marks_obtained: 72,
    marks_possible: 100,
    retrigger_count: 0,
    student_id: "student-1",
    student_name: "Arjun Student",
    student_email: "arjun@example.com",
  }]);
  vi.spyOn(window, "open").mockImplementation(() => null);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("EvaluationPaperManager", () => {
  it("shows published papers as subject-grouped management cards", async () => {
    render(<EvaluationPaperManager />);

    expect(await screen.findByText("Business law 100%")).toBeTruthy();
    expect(screen.getAllByText("Business Laws").length).toBeGreaterThan(0);
    expect(screen.getByText("11 submissions")).toBeTruthy();
    expect(screen.getByText("Rubric ready")).toBeTruthy();
    expect(screen.getByText("Published")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Question PDF" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Answers PDF" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Extracted Text" })).toBeTruthy();
  });

  it("loads the full paper on demand and shows formatted and raw extraction tabs", async () => {
    const user = userEvent.setup();
    render(<EvaluationPaperManager />);
    await screen.findByText("Business law 100%");

    await user.click(screen.getByRole("button", { name: "Extracted Text" }));

    const dialog = await screen.findByRole("dialog", { name: "Extracted paper text" });
    expect(getPaper).toHaveBeenCalledWith("paper-1");
    expect(within(dialog).getAllByText("Question No. 1 is compulsory.", { exact: false })).toHaveLength(2);
    expect(within(dialog).getByText("Raw — exactly as stored in the DB")).toBeTruthy();

    await user.click(within(dialog).getByRole("tab", { name: /Suggested Answers/ }));
    expect(within(dialog).getAllByText("1(a) The contract is enforceable when...", { exact: false })).toHaveLength(2);

    await user.click(within(dialog).getByRole("tab", { name: /Grading Schema/ }));
    expect(within(dialog).getByText("Explain the legal position.")).toBeTruthy();
    expect(within(dialog).getByText("States the provision")).toBeTruthy();
  });

  it("opens the paper's student submissions with answer-sheet and report actions", async () => {
    const user = userEvent.setup();
    render(<EvaluationPaperManager />);
    await screen.findByText("Business law 100%");

    await user.click(screen.getByRole("button", { name: "View 11 submissions for Business law 100%" }));

    const dialog = await screen.findByRole("dialog", { name: "Student submissions" });
    await waitFor(() => expect(listPaperSubmissions).toHaveBeenCalledWith("paper-1"));
    expect(within(dialog).getByText("Arjun Student")).toBeTruthy();
    expect(within(dialog).getByText("arjun@example.com")).toBeTruthy();
    expect(within(dialog).getByText("72/100")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Answer Sheet" })).toBeTruthy();
    expect(within(dialog).getByRole("link", { name: "View Report" }).getAttribute("href")).toBe(
      "/dashboard/teacher/handwritten-evaluation/submissions/submission-1",
    );
  });

  it("unpublishes through the existing paper update endpoint", async () => {
    const user = userEvent.setup();
    render(<EvaluationPaperManager />);
    await screen.findByText("Business law 100%");

    await user.click(screen.getByRole("button", { name: "Unpublish" }));

    await waitFor(() => expect(updatePaper).toHaveBeenCalledWith("paper-1", { is_active: false }));
    expect(await screen.findByText("Paper unpublished.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Publish" })).toBeTruthy();
  });

  it("loads the full ExamApp-style edit workflow and saves only changed fields", async () => {
    const user = userEvent.setup();
    render(<EvaluationPaperManager />);
    await screen.findByText("Business law 100%");

    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit evaluation paper" });
    expect(getPaper).toHaveBeenCalledWith("paper-1");
    expect(within(dialog).getByText("Edit question paper")).toBeTruthy();
    expect(within(dialog).getByText("Current suggested answers will be retained")).toBeTruthy();

    const title = within(dialog).getByLabelText(/Paper title/);
    await user.clear(title);
    await user.type(title, "Updated business law paper");
    const replacement = new File(["%PDF-1.4 replacement"], "replacement.pdf", { type: "application/pdf" });
    await user.upload(within(dialog).getByLabelText("Question paper"), replacement);
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updatePaper).toHaveBeenCalledWith("paper-1", {
      title: "Updated business law paper",
      question_paper: replacement,
    }));
    expect(await screen.findByText(/Fresh extraction and rubric generation have been queued/)).toBeTruthy();
  });
});
