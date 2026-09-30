import type {
  EvaluationQuestionReport,
  HandwrittenEvaluationReport,
} from "@/lib/api";

export type ReportTone = "strong" | "on-track" | "revision" | "neutral" | "warning";

export type ReportLevel = {
  label: string;
  percentage: number | null;
  tone: ReportTone;
};

export type QuestionGuidance = {
  label: string;
  title: string;
  score: number;
  total: number;
  scoreLabel: string;
  level: ReportLevel;
  state: "evaluated" | "not_attempted" | "not_counted" | "not_evaluated";
  statusDescription: string;
  studentAnswer: string;
  didWell: string;
  improvements: string[];
  mistakes: { mistake: string; expected: string }[];
  expectedPoints: string[];
  feedback: string;
};

export function formatEvaluationMark(value: number): string {
  return Number.isInteger(Number(value)) ? String(Number(value)) : Number(value).toFixed(1);
}

function unique(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  return values
    .map((value) => String(value ?? "").replace(/\s+/g, " ").trim())
    .filter((value) => {
      const key = value.toLowerCase();
      if (!value || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function questionState(question: EvaluationQuestionReport): QuestionGuidance["state"] {
  if (question.not_evaluated) return "not_evaluated";
  if (question.not_attempted && !question.not_counted) return "not_attempted";
  if (question.not_counted) return "not_counted";
  return "evaluated";
}

export function evaluationLevel(score: number, total: number, state = "evaluated"): ReportLevel {
  if (state !== "evaluated") {
    const label = state === "not_counted"
      ? "Not Counted"
      : state === "not_attempted"
        ? "Not Answered"
        : "Needs Review";
    return { label, percentage: null, tone: state === "not_evaluated" ? "warning" : "neutral" };
  }
  const percentage = total > 0 ? Math.round((score / total) * 100) : 0;
  if (percentage >= 75) return { label: "Strong", percentage, tone: "strong" };
  if (percentage >= 50) return { label: "On Track", percentage, tone: "on-track" };
  return { label: "Needs Revision", percentage, tone: "revision" };
}

function statusDescription(state: QuestionGuidance["state"]): string {
  if (state === "not_counted") {
    return "This response is shown for reference, but its marks are excluded from the total.";
  }
  if (state === "not_attempted") {
    return "No answer was found for this required question, so it is counted as zero.";
  }
  if (state === "not_evaluated") {
    return "The evaluator could not produce a reliable score. Faculty review is required.";
  }
  return "";
}

export function buildQuestionGuidance(question: EvaluationQuestionReport): QuestionGuidance {
  const state = questionState(question);
  const score = Number(question.marks_obtained) || 0;
  const total = Number(question.marks_possible) || 0;
  const level = evaluationLevel(score, total, state);
  const unmet = question.criteria_breakdown.filter(
    (criterion) => Number(criterion.marks_awarded) < Number(criterion.marks_available),
  );
  const successful = question.criteria_breakdown.filter(
    (criterion) => Number(criterion.marks_awarded) > 0,
  );
  const improvements = unique([
    ...(question.student_guidance.improve_next ?? []),
    ...unmet.map((criterion) => criterion.comment),
    question.feedback,
  ]).slice(0, 4);
  const expectedPoints = unique(
    question.criteria_breakdown.flatMap((criterion) => [
      criterion.correct_treatment,
      criterion.criterion,
    ]),
  ).slice(0, 6);
  const mistakes = unmet.slice(0, 5).map((criterion, index) => ({
    mistake: criterion.comment || improvements[index] || "This part was not fully addressed.",
    expected: criterion.correct_treatment || criterion.criterion || "Review the expected treatment for this point.",
  }));
  const didWell = question.student_guidance.what_you_did_well
    || successful[0]?.comment
    || successful[0]?.criterion
    || (score > 0
      ? "You included relevant points and earned credit for this response."
      : "Your attempt provides a clear starting point for revision.");

  return {
    label: question.question_ref || "Question",
    title: question.question_text || "",
    score,
    total,
    scoreLabel: state === "not_evaluated"
      ? `—/${formatEvaluationMark(total)}`
      : `${formatEvaluationMark(score)}/${formatEvaluationMark(total)}`,
    level,
    state,
    statusDescription: statusDescription(state),
    studentAnswer: question.student_answer_excerpt || "",
    didWell,
    improvements: improvements.length
      ? improvements
      : ["Keep the answer direct, complete, and clearly linked to the question."],
    mistakes,
    expectedPoints,
    feedback: question.feedback || "",
  };
}

export function buildHandwrittenReportView(report: HandwrittenEvaluationReport) {
  const score = Number(report.total_score) || 0;
  const total = Number(report.total_marks) || 0;
  const level = evaluationLevel(score, total);
  const guidance = report.questions.map(buildQuestionGuidance);
  const strengths = unique(report.strengths)
    .filter((value) => value.length >= 8 && !/^q\s*\d+[a-z0-9().-]*$/i.test(value))
    .slice(0, 4);
  const nextSteps = unique([
    ...report.areas_to_improve,
    ...guidance
      .filter((item) => item.state === "evaluated")
      .flatMap((item) => item.improvements),
    "Revise the lowest-scoring answer first, then attempt it again under time limits.",
    "Use clear headings, direct application, and a supported conclusion in every answer.",
  ]).slice(0, 3);
  const summary = report.overall_feedback || (
    level.label === "Strong"
      ? "You are performing strongly; keep refining precision and completeness."
      : level.label === "On Track"
        ? "You are on the right path; focused revision can lift your score further."
        : "Focus on the expected answer points below to build a stronger next attempt."
  );
  return { score, total, level, guidance, strengths, nextSteps, summary };
}
