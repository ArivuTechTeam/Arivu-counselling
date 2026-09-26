import { describe, expect, it } from "vitest";
import type { ApiCallLog } from "./api";
import { callStage, conversionRate, groupApiLogs } from "./api-log-display";

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
    expect(callStage("quiz_generation")).toBe("Quiz generation");
    expect(callStage("topic_extraction_map")).toBe("Extraction — topic mapping");
    expect(callStage("future_stage")).toBe("future stage");
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
