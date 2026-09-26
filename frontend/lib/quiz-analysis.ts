// Smart Analysis — pure, client-side computation over a graded attempt.
//
// Everything here is derived from data the results API ALREADY returns
// (is_correct, marks, type, student_answer, suggested_seconds) plus per-question
// time we track in the browser while the student takes the quiz. No backend.
//
// NOTE: per-question topic/chapter/difficulty are NOT in the student results
// payload, so topic-level "weak areas" is intentionally NOT computed here — that
// needs a small backend addition later. We analyse by QUESTION TYPE instead,
// which is available today.

export type AnalysisQuestion = {
  id: string;
  type: string;
  marks?: number | null;
  suggested_seconds?: number | null;
  is_correct: boolean | null;
  student_answer?: unknown;
};

/** Answered = a non-empty answer was given. Mirrors the taking view's rule. */
export function isAttempted(value: unknown): boolean {
  if (value === undefined || value === null || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

export type ScoreSummary = {
  total: number;
  attempted: number;
  correct: number;
  wrong: number;
  skipped: number;
  accuracy: number; // correct / attempted, %
  score: number;
  maxScore: number;
  scorePct: number; // score / maxScore, %
};

export function summarize(
  questions: AnalysisQuestion[],
  score: number,
  maxScore: number,
): ScoreSummary {
  let attempted = 0;
  let correct = 0;
  for (const q of questions) {
    if (!isAttempted(q.student_answer)) continue;
    attempted += 1;
    if (q.is_correct === true) correct += 1;
  }
  const total = questions.length;
  const wrong = attempted - correct;
  const skipped = total - attempted;
  return {
    total,
    attempted,
    correct,
    wrong,
    skipped,
    accuracy: attempted ? Math.round((correct / attempted) * 100) : 0,
    score,
    maxScore,
    scorePct: maxScore > 0 ? Math.round((score / maxScore) * 100) : 0,
  };
}

export type TypeStat = {
  type: string;
  total: number;
  attempted: number;
  correct: number;
  accuracy: number; // correct / attempted, %
};

/** Correct/attempted per question type — the client-side stand-in for
 *  "weak vs strong areas" until per-question topic tags exist server-side. */
export function byType(questions: AnalysisQuestion[]): TypeStat[] {
  const map = new Map<string, TypeStat>();
  for (const q of questions) {
    const stat =
      map.get(q.type) ?? { type: q.type, total: 0, attempted: 0, correct: 0, accuracy: 0 };
    stat.total += 1;
    if (isAttempted(q.student_answer)) {
      stat.attempted += 1;
      if (q.is_correct === true) stat.correct += 1;
    }
    map.set(q.type, stat);
  }
  const out = Array.from(map.values());
  for (const s of out) s.accuracy = s.attempted ? Math.round((s.correct / s.attempted) * 100) : 0;
  // Weakest first, so the review naturally leads with what to fix.
  return out.sort((a, b) => a.accuracy - b.accuracy);
}

// Embibe-style attempt quality — needs per-question time + a suggested pace.
export type AttemptQuality =
  | "unattempted"
  | "perfect" // correct, within pace
  | "overtime_correct" // correct but slow
  | "too_fast_wrong" // wrong and rushed (careless)
  | "overtime_wrong" // wrong and slow (struggled)
  | "wrong_normal" // wrong, ordinary pace
  | "correct_untimed" // correct, no timing available
  | "wrong_untimed"; // wrong, no timing available

export function attemptQuality(
  q: AnalysisQuestion,
  timeSeconds?: number,
): AttemptQuality {
  if (!isAttempted(q.student_answer)) return "unattempted";
  const correct = q.is_correct === true;
  const suggested = q.suggested_seconds ?? 0;
  const timed = typeof timeSeconds === "number" && timeSeconds >= 0 && suggested > 0;
  if (!timed) return correct ? "correct_untimed" : "wrong_untimed";
  const t = timeSeconds as number;
  if (correct) return t <= suggested ? "perfect" : "overtime_correct";
  if (t < suggested * 0.4) return "too_fast_wrong";
  if (t > suggested) return "overtime_wrong";
  return "wrong_normal";
}

export type QualityCounts = Record<AttemptQuality, number>;

export function qualityCounts(
  questions: AnalysisQuestion[],
  times: Record<string, number>,
): QualityCounts {
  const counts: QualityCounts = {
    unattempted: 0,
    perfect: 0,
    overtime_correct: 0,
    too_fast_wrong: 0,
    overtime_wrong: 0,
    wrong_normal: 0,
    correct_untimed: 0,
    wrong_untimed: 0,
  };
  for (const q of questions) counts[attemptQuality(q, times[q.id])] += 1;
  return counts;
}

/** True when we have usable per-question timing for enough questions to make the
 *  attempt-quality view meaningful (otherwise the UI hides it). */
export function hasTimingSignal(
  questions: AnalysisQuestion[],
  times: Record<string, number>,
): boolean {
  const timed = questions.filter(
    (q) => (q.suggested_seconds ?? 0) > 0 && typeof times[q.id] === "number",
  ).length;
  return timed >= Math.max(1, Math.ceil(questions.length / 2));
}

/** Short, plain-English coaching lines from the quality distribution. */
export function insightSentences(counts: QualityCounts): string[] {
  const out: string[] = [];
  if (counts.too_fast_wrong > 0)
    out.push(
      `You rushed ${counts.too_fast_wrong} question${counts.too_fast_wrong === 1 ? "" : "s"} — answered too fast and got ${counts.too_fast_wrong === 1 ? "it" : "them"} wrong. Slow down.`,
    );
  if (counts.overtime_wrong > 0)
    out.push(
      `You spent too long on ${counts.overtime_wrong} question${counts.overtime_wrong === 1 ? "" : "s"} and still missed ${counts.overtime_wrong === 1 ? "it" : "them"} — revise these topics.`,
    );
  if (counts.overtime_correct > 0)
    out.push(
      `${counts.overtime_correct} correct answer${counts.overtime_correct === 1 ? "" : "s"} took longer than the pace — practise for speed.`,
    );
  if (counts.perfect > 0)
    out.push(
      `${counts.perfect} perfect attempt${counts.perfect === 1 ? "" : "s"} — correct and on pace. Keep it up!`,
    );
  return out;
}

export type TimeBuckets = {
  correctSec: number;
  wrongSec: number;
  skippedSec: number;
  totalSec: number;
};

/** Total time split across correct / wrong / skipped questions. */
export function timeBuckets(
  questions: AnalysisQuestion[],
  times: Record<string, number>,
): TimeBuckets {
  let correctSec = 0;
  let wrongSec = 0;
  let skippedSec = 0;
  for (const q of questions) {
    const t = times[q.id] ?? 0;
    if (!isAttempted(q.student_answer)) skippedSec += t;
    else if (q.is_correct === true) correctSec += t;
    else wrongSec += t;
  }
  return { correctSec, wrongSec, skippedSec, totalSec: correctSec + wrongSec + skippedSec };
}
