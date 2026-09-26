import { describe, expect, it } from "vitest";
import type { ApiCallLog } from "./api";
import { callStage, conversionRate, costActivityCopy, groupApiLogs } from "./api-log-display";

function call(overrides: Partial<ApiCallLog> = {}): ApiCallLog {
  return {
    id: "call-1", tenant_id: "tenant-1", document_id: "paper-1", job_id: null, workflow_id: null,
    call_type: "quiz_generation", provider: "gemini", model: "gemini-3.5-flash",
    was_fallback: false, input_tokens: 12, output_tokens: 4,
    cached_tokens: null, thinking_tokens: null, cost_usd: 0.1, cost_inr: 8.3,
    latency_ms: 50, status: "success", error_message: null,
    created_at: "2026-09-26T00:00:00Z", ...overrides,
  };
}

describe("safe API log display", () => {
  it("labels known stages and handles new call types", () => {
    expect(callStage("quiz_generation")).toBe("Writing quiz questions");
    expect(callStage("topic_extraction_map")).toBe("Finding topics in document sections");
    expect(callStage("future_stage")).toBe("future stage");
  });
  it("describes document analysis without claiming it is old or failed", () => {
    const copy = costActivityCopy({ kind: "legacy", workflow_id: null,
      stages: [{ call_type: "single_call_topic_analysis", calls: 3, cost_usd: 1 }] });
    expect(copy.title).toBe("Document topic analysis");
    expect(copy.description).toContain("repeated analysis");
    expect(copy.description).not.toMatch(/historical|older|failed/);
  });
  it.each([["question_verification", "Answer checking"], ["question_regeneration", "Question rewriting"]])(
    "explains %s requests with missing links", (call_type, title) => {
      const copy = costActivityCopy({ kind: "unlinked", workflow_id: null,
        stages: [{ call_type, calls: 11, cost_usd: 1 }] });
      expect(copy.title).toBe(title);
      expect(copy.description).toContain("no saved document or quiz link");
      expect(copy.description).toContain("does not mean the requests are old or failed");
    });
  it("does not guess what mixed or unknown untracked activity represents", () => {
    for (const stages of [[], [{ call_type: "future_stage", calls: 1, cost_usd: null }],
      [{ call_type: "single_call_topic_analysis", calls: 1, cost_usd: 1 }, { call_type: "quiz_generation", calls: 1, cost_usd: 1 }]]) {
      expect(costActivityCopy({ kind: "legacy", workflow_id: null, stages }).title).toBe("Other AI activity");
    }
  });
  it("keeps quiz creation and imports separate from analysis and later edits", () => {
    for (const kind of ["generation", "extraction"] as const) {
      const copy = costActivityCopy({ kind, workflow_id: "run-1", stages: [] });
      expect(copy.title).toBe(kind === "generation" ? "Creating a quiz" : "Creating a quiz from existing questions");
      expect(copy.description).toContain("Document analysis and later question edits are separate");
    }
  });
  it("accepts only positive finite exchange rates", () => {
    expect(conversionRate("85.5")).toBe(85.5);
    for (const value of ["", "0", "-1", "Infinity", "invalid"]) {
      expect(conversionRate(value)).toBeNull();
    }
  });
  it("groups only the supplied page and separates tenant, job and call scopes", () => {
    const groups = groupApiLogs([
      call(), call({ id: "call-2" }),
      call({ id: "call-3", tenant_id: "tenant-2" }),
      call({ id: "call-4", document_id: null, job_id: "paper-1" }),
      call({ id: "call-5", document_id: null }),
      call({ id: "call-6", document_id: null }),
    ]);
    expect(groups.map(([, rows]) => rows.length)).toEqual([2, 1, 1, 1, 1]);
    expect(groupApiLogs([])).toEqual([]);
  });
});
