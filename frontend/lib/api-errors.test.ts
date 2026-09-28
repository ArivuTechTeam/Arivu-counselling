import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/public-env", () => ({
  PUBLIC_ENV: { apiBaseUrl: "http://localhost:8000" },
}));
vi.mock("@/lib/supabase", () => ({
  createClient: () => ({
    auth: { getSession: async () => ({ data: { session: null } }) },
  }),
}));
vi.mock("@/lib/safe-next", () => ({
  safeDashboardNext: (path: string) => path,
}));

import { ApiRequestError, finalizeAttemptForExit, getDashboardProfile } from "./api";

describe("shared API errors used by all dashboard roles", () => {
  beforeEach(() => {
    vi.stubGlobal("window", { setTimeout, clearTimeout });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([
    [400, "No approved questions match this selection.", "no_questions_available"],
    [403, "You do not have permission to edit this course.", null],
    [503, "The data service is temporarily unavailable. Please try again.", null],
  ])("shows an actionable %i response without its request ID", async (status, detail, reason) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail, request_id: "private-trace-123" }),
      {
        status,
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": "private-trace-123",
          ...(reason ? { "X-Error-Code": reason } : {}),
        },
      },
    )));

    await expect(getDashboardProfile()).rejects.toMatchObject({
      message: detail,
      requestId: "private-trace-123",
      reason,
    });
  });

  it("hides internal 500 details while offering a next step", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "private database error", request_id: "private-trace-500" }),
      { status: 500, headers: { "X-Request-ID": "private-trace-500" } },
    )));

    try {
      await getDashboardProfile();
      throw new Error("Expected the API call to fail.");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiRequestError);
      const apiError = error as ApiRequestError;
      expect(apiError.requestId).toBe("private-trace-500");
      expect(apiError.message).toContain("contact support");
      expect(apiError.message).not.toContain("private");
      expect(apiError.message).not.toContain("reference");
    }
  });

  it("does not treat a rejected exit submission as a completed attempt", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "This attempt is still in progress." }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    )));

    await expect(finalizeAttemptForExit("attempt-1", "quiz", [])).rejects.toBeInstanceOf(
      ApiRequestError,
    );
  });
});
