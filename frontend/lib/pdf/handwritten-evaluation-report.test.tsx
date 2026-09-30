import path from "node:path";

import { Font, renderToBuffer } from "@react-pdf/renderer";
import { createElement } from "react";
import { beforeAll, describe, expect, it } from "vitest";

import type { HandwrittenEvaluationReport } from "@/lib/api";
import { HandwrittenEvaluationReportDoc } from "./handwritten-evaluation-report";

beforeAll(() => {
  const family = Font.getRegisteredFonts()["Noto Sans"];
  const sources = family.sources as Array<{
    src: string;
    fontWeight: number;
    data: unknown;
    loadResultPromise: Promise<void> | null;
  }>;
  for (const source of sources) {
    source.src = path.resolve(
      source.fontWeight === 700
        ? "public/fonts/NotoSans-Bold.ttf"
        : "public/fonts/NotoSans-Regular.ttf",
    );
    source.data = null;
    source.loadResultPromise = null;
  }
});

function longReport(): HandwrittenEvaluationReport {
  const observedAnswerLengths = [
    593, 900, 539, 1363, 858, 413, 1116, 1458, 864,
    0, 1731, 227, 300, 1001, 682, 0, 0, 0,
  ];

  const answerFor = (targetLength: number) => {
    if (!targetLength) return "";
    const lines = Array.from(
      { length: Math.ceil(targetLength / 82) },
      (_, index) =>
        `${index + 1}. Apply the relevant provision to each material fact and state the supported conclusion.`,
    );
    return lines.join("\n\n").slice(0, targetLength);
  };

  return {
    submission_id: "76a6e080-5c8e-44ab-b8fe-3fb4d976622b",
    status: "completed",
    submission_date: "2026-09-30T04:11:00.550882+00:00",
    evaluation_date: "2026-09-30T04:14:36.513421+00:00",
    paper: {
      id: "18844cee-bd11-4381-9077-650b7d724690",
      title: "Business Law Paper 2",
      subject: "Business Law",
      total_marks: 100,
    },
    student: { name: "Arjun", email: "arjun@gmail.com" },
    total_score: 43,
    total_marks: 100,
    percentage: 43,
    overall_feedback:
      "Evaluation completed from the fixed rubric; review flagged items before relying on the result.",
    strengths: ["Clear application in the strongest response"],
    areas_to_improve: ["State complete provisions and conclusions"],
    requires_review: true,
    answer_script_url: null,
    questions: Array.from({ length: 18 }, (_, index) => ({
      question_ref: `${Math.floor(index / 3) + 1}(${String.fromCharCode(97 + (index % 3))})`,
      question_text: "Apply the relevant legal provision and reach a supported conclusion.",
      marks_obtained: index % 4,
      marks_possible: 7,
      not_attempted: false,
      not_evaluated: false,
      not_counted: false,
      mapping_status: "matched" as const,
      feedback: "The response identifies part of the rule but needs a more complete application.",
      student_guidance: {
        what_you_did_well: "You identified a relevant principle.",
        improve_next: ["State the complete rule", "Apply every material fact"],
      },
      student_answer_excerpt: answerFor(observedAnswerLengths[index]),
      handwriting_legibility: "medium",
      grading_confidence: 0.82,
      criteria_breakdown: [
        {
          criterion_id: `criterion-${index}`,
          criterion: "Correct provision and application",
          marks_awarded: index % 4,
          marks_available: 7,
          comment: "Application is incomplete.",
          correct_treatment: "State the full provision before applying it.",
        },
      ],
    })),
  };
}

describe("HandwrittenEvaluationReportDoc", () => {
  it(
    "renders long multi-question transcripts across A4 pages",
    async () => {
      const buffer = await renderToBuffer(
        createElement(HandwrittenEvaluationReportDoc, {
          report: longReport(),
          branding: {
            name: "Bright Future University",
            primary_color: "#143A6B",
          },
        }),
      );

      expect(buffer.subarray(0, 4).toString()).toBe("%PDF");
      expect(buffer.byteLength).toBeGreaterThan(10_000);
      const pageCount = buffer.toString("latin1").match(/\/Type \/Page\b/g)?.length ?? 0;
      expect(pageCount).toBeGreaterThan(1);
      expect(pageCount).toBeLessThan(20);
    },
    30_000,
  );
});
