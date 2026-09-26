import { describe, expect, it } from "vitest";

import {
  AnalysisQuestion,
  attemptQuality,
  byType,
  hasTimingSignal,
  insightSentences,
  isAttempted,
  qualityCounts,
  summarize,
  timeBuckets,
} from "./quiz-analysis";

const q = (over: Partial<AnalysisQuestion>): AnalysisQuestion => ({
  id: "x",
  type: "mcq_single",
  suggested_seconds: 60,
  is_correct: null,
  student_answer: null,
  ...over,
});

describe("isAttempted", () => {
  it("treats null/empty/empty-array as not attempted", () => {
    expect(isAttempted(null)).toBe(false);
    expect(isAttempted("")).toBe(false);
    expect(isAttempted([])).toBe(false);
    expect(isAttempted("A")).toBe(true);
    expect(isAttempted(["a"])).toBe(true);
    expect(isAttempted(0)).toBe(true);
  });
});

describe("summarize", () => {
  it("counts correct/wrong/skipped and rates", () => {
    const qs = [
      q({ id: "1", student_answer: "a", is_correct: true }),
      q({ id: "2", student_answer: "a", is_correct: false }),
      q({ id: "3", student_answer: null, is_correct: null }), // skipped
      q({ id: "4", student_answer: "a", is_correct: true }),
    ];
    const s = summarize(qs, 4, 8);
    expect(s).toMatchObject({
      total: 4,
      attempted: 3,
      correct: 2,
      wrong: 1,
      skipped: 1,
      accuracy: 67, // 2/3
      scorePct: 50, // 4/8
    });
  });
});

describe("byType", () => {
  it("aggregates accuracy per type, weakest first", () => {
    const qs = [
      q({ id: "1", type: "mcq_single", student_answer: "a", is_correct: true }),
      q({ id: "2", type: "mcq_single", student_answer: "a", is_correct: true }),
      q({ id: "3", type: "numerical", student_answer: "a", is_correct: false }),
    ];
    const stats = byType(qs);
    expect(stats[0]).toMatchObject({ type: "numerical", accuracy: 0 }); // weakest first
    expect(stats[1]).toMatchObject({ type: "mcq_single", accuracy: 100 });
  });
});

describe("attemptQuality", () => {
  it("labels unattempted", () => {
    expect(attemptQuality(q({ student_answer: null }))).toBe("unattempted");
  });
  it("perfect = correct within pace; overtime_correct = correct but slow", () => {
    expect(attemptQuality(q({ student_answer: "a", is_correct: true, suggested_seconds: 60 }), 40)).toBe("perfect");
    expect(attemptQuality(q({ student_answer: "a", is_correct: true, suggested_seconds: 60 }), 90)).toBe("overtime_correct");
  });
  it("too_fast_wrong = wrong and rushed; overtime_wrong = wrong and slow", () => {
    expect(attemptQuality(q({ student_answer: "a", is_correct: false, suggested_seconds: 60 }), 10)).toBe("too_fast_wrong");
    expect(attemptQuality(q({ student_answer: "a", is_correct: false, suggested_seconds: 60 }), 90)).toBe("overtime_wrong");
    expect(attemptQuality(q({ student_answer: "a", is_correct: false, suggested_seconds: 60 }), 40)).toBe("wrong_normal");
  });
  it("falls back to untimed labels when no time/pace", () => {
    expect(attemptQuality(q({ student_answer: "a", is_correct: true }), undefined)).toBe("correct_untimed");
    expect(attemptQuality(q({ student_answer: "a", is_correct: false, suggested_seconds: 0 }), 30)).toBe("wrong_untimed");
  });
});

describe("qualityCounts + insights", () => {
  it("counts categories and produces coaching lines", () => {
    const qs = [
      q({ id: "1", student_answer: "a", is_correct: false, suggested_seconds: 60 }), // rushed
      q({ id: "2", student_answer: "a", is_correct: true, suggested_seconds: 60 }), // perfect
    ];
    const times = { "1": 10, "2": 30 };
    const counts = qualityCounts(qs, times);
    expect(counts.too_fast_wrong).toBe(1);
    expect(counts.perfect).toBe(1);
    const lines = insightSentences(counts);
    expect(lines.some((l) => l.includes("rushed"))).toBe(true);
    expect(lines.some((l) => l.includes("perfect"))).toBe(true);
  });
});

describe("hasTimingSignal", () => {
  it("requires timing for at least half the questions", () => {
    const qs = [q({ id: "1" }), q({ id: "2" }), q({ id: "3" }), q({ id: "4" })];
    expect(hasTimingSignal(qs, { "1": 10 })).toBe(false); // 1/4
    expect(hasTimingSignal(qs, { "1": 10, "2": 20 })).toBe(true); // 2/4
  });
});

describe("timeBuckets", () => {
  it("splits time across correct/wrong/skipped", () => {
    const qs = [
      q({ id: "1", student_answer: "a", is_correct: true }),
      q({ id: "2", student_answer: "a", is_correct: false }),
      q({ id: "3", student_answer: null }),
    ];
    const b = timeBuckets(qs, { "1": 30, "2": 45, "3": 5 });
    expect(b).toEqual({ correctSec: 30, wrongSec: 45, skippedSec: 5, totalSec: 80 });
  });
});
