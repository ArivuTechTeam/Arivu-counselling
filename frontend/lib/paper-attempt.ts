import type { PaperTakeQuestion } from "@/lib/api";

export function isPaperAnswerComplete(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return false;
  if (typeof value === "string") return value.trim().length > 0;
  return !Array.isArray(value) || value.length > 0;
}

export function canSubmitPaper(
  questions: PaperTakeQuestion[],
  answers: Record<string, unknown>,
): boolean {
  return questions.length > 0 && questions.every((question) =>
    isPaperAnswerComplete(answers[question.id]),
  );
}
