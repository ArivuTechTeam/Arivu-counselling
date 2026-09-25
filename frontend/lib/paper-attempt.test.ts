import { describe, expect, it } from "vitest";

import type { PaperTakeQuestion } from "./api";
import { canSubmitPaper, isPaperAnswerComplete } from "./paper-attempt";

const questions = [
  { id: "q1", type: "mcq_single", question_text: "First" },
  { id: "q2", type: "mcq_multi", question_text: "Second" },
] as PaperTakeQuestion[];

describe("paper attempt completion", () => {
  it("requires an answer to every question before report submission", () => {
    expect(canSubmitPaper(questions, { q1: "a", q2: [] })).toBe(false);
    expect(canSubmitPaper(questions, { q1: "a", q2: ["b"] })).toBe(true);
    expect(canSubmitPaper([], {})).toBe(false);
  });

  it("treats zero as a valid numerical answer but rejects blanks", () => {
    expect(isPaperAnswerComplete(0)).toBe(true);
    expect(isPaperAnswerComplete("")).toBe(false);
    expect(isPaperAnswerComplete("   ")).toBe(false);
    expect(isPaperAnswerComplete(null)).toBe(false);
  });
});
