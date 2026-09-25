import type { StudentQuiz } from "@/lib/api";

/** Count available actions, never submitted-answer rows or graded attempts. */
export function countQuizActions(quizzes: StudentQuiz[]) {
  let newQuizzes = 0;
  let revisitQuizzes = 0;

  for (const quiz of quizzes) {
    for (const variant of quiz.variants) {
      if (variant.attempts_remaining <= 0) continue;
      if (variant.attempted) revisitQuizzes += 1;
      else newQuizzes += 1;
    }
  }

  return { newQuizzes, revisitQuizzes };
}
