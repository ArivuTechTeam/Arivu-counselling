import { describe, expect, it } from "vitest";

import type { StudentQuiz } from "./api";
import { countQuizActions } from "./student-dashboard-metrics";

function quiz(
  attempted: boolean,
  attemptsRemaining: number,
  questionCount = 259,
): StudentQuiz {
  return {
    id: "quiz-1",
    title: "Chapter 1",
    variants: [{
      id: "variant-1",
      variant_type: "mixed",
      question_count: questionCount,
      attempted,
      attempt_count: attempted ? 1 : 0,
      attempt_limit: 10,
      attempts_remaining: attemptsRemaining,
    }],
  };
}

describe("student dashboard action metrics", () => {
  it("does not present an early-exit 259-question quiz as progress", () => {
    expect(countQuizActions([quiz(false, 10)])).toEqual({ newQuizzes: 1, revisitQuizzes: 0 });
    expect(countQuizActions([quiz(true, 9)])).toEqual({ newQuizzes: 0, revisitQuizzes: 1 });
  });

  it("does not count exhausted quizzes as available actions", () => {
    expect(countQuizActions([quiz(true, 0), quiz(false, 0)])).toEqual({
      newQuizzes: 0,
      revisitQuizzes: 0,
    });
  });
});
