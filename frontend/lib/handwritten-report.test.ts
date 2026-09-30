import { describe, expect, it } from "vitest";

import type { HandwrittenEvaluationReport } from "./api";
import { buildHandwrittenReportView } from "./handwritten-report";

const report: HandwrittenEvaluationReport = {
  submission_id: "submission-1",
  status: "completed",
  submission_date: "2026-09-29T00:00:00Z",
  evaluation_date: "2026-09-29T00:03:00Z",
  paper: { id: "paper-1", title: "Business Law", subject: "Law", total_marks: 100 },
  student: { name: "Arjun", email: "arjun@example.com" },
  total_score: 64,
  total_marks: 100,
  percentage: 64,
  overall_feedback: "Good application; improve conclusions.",
  strengths: ["Applied the core rule correctly", "Q1"],
  areas_to_improve: ["State a supported conclusion"],
  requires_review: false,
  questions: [{
    question_ref: "Q1",
    question_text: "Explain the rule.",
    marks_obtained: 6,
    marks_possible: 10,
    not_attempted: false,
    not_evaluated: false,
    not_counted: false,
    mapping_status: "matched",
    feedback: "Apply the rule to the facts.",
    student_guidance: { what_you_did_well: "Correct rule", improve_next: ["Conclude clearly"] },
    student_answer_excerpt: "The rule applies...",
    handwriting_legibility: "clear",
    grading_confidence: 1,
    criteria_breakdown: [{
      criterion_id: "c1",
      criterion: "Rule and application",
      marks_awarded: 6,
      marks_available: 10,
      comment: "The conclusion was incomplete.",
      correct_treatment: "State the conclusion after applying the rule.",
    }],
  }],
};

describe("handwritten student report view", () => {
  it("matches the ExamApp-style overview and paired mistake guidance", () => {
    const view = buildHandwrittenReportView(report);
    expect(view.level).toMatchObject({ label: "On Track", percentage: 64 });
    expect(view.strengths).toEqual(["Applied the core rule correctly"]);
    expect(view.nextSteps[0]).toBe("State a supported conclusion");
    expect(view.guidance[0]).toMatchObject({
      label: "Q1",
      scoreLabel: "6/10",
      studentAnswer: "The rule applies...",
      didWell: "Correct rule",
    });
    expect(view.guidance[0].mistakes[0]).toEqual({
      mistake: "The conclusion was incomplete.",
      expected: "State the conclusion after applying the rule.",
    });
  });

  it("keeps unscored questions visibly absent from the numeric score", () => {
    const value = structuredClone(report);
    value.questions[0].not_evaluated = true;
    const item = buildHandwrittenReportView(value).guidance[0];
    expect(item.scoreLabel).toBe("—/10");
    expect(item.level.label).toBe("Needs Review");
  });
});
