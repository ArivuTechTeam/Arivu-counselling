import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/public-env", () => ({
  PUBLIC_ENV: { apiBaseUrl: "http://localhost:8000" },
}));
vi.mock("@/lib/supabase", () => ({
  createClient: () => ({
    auth: {
      getSession: async () => ({
        data: { session: { access_token: "student-token" } },
      }),
    },
  }),
}));
vi.mock("@/lib/safe-next", () => ({
  safeDashboardNext: (path: string) => path,
}));

import {
  ApiRequestError,
  getHandwrittenAnalytics,
  getHandwrittenMistakes,
  getHandwrittenRevisionItems,
  getHandwrittenWeakAreas,
} from "./api";

const BASE = "http://localhost:8000/api/v1/handwritten-learning";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("handwritten learning API", () => {
  beforeEach(() => {
    vi.stubGlobal("window", { setTimeout, clearTimeout });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("sends filters as query params and unwraps the list", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ mistakes: [{ id: "m1" }] }))
      .mockResolvedValueOnce(jsonResponse({ revision_items: [{ id: "r1" }] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      getHandwrittenMistakes({ subjectId: "subject-1", severity: "major" }),
    ).resolves.toEqual([{ id: "m1" }]);
    await expect(
      getHandwrittenRevisionItems({ subjectId: "subject-1", resolved: false }),
    ).resolves.toEqual([{ id: "r1" }]);

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      `${BASE}/mistakes?subject_id=subject-1&severity=major`,
      `${BASE}/revision-items?subject_id=subject-1&resolved=false`,
    ]);
  });

  it("sends the bearer token and no query string when unfiltered", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ mistakes: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await getHandwrittenMistakes();

    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/mistakes`);
    const headers = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(headers.get("Authorization")).toBe("Bearer student-token");
  });

  // Isolation: the client has no way to ask for another student's data.
  // Even a crafted call that smuggles a student id in must not reach the URL.
  it("never sends a student_id, even when one is passed in", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse({
      mistakes: [], revision_items: [], weak_chapters: [], mistake_patterns: [],
    }));
    vi.stubGlobal("fetch", fetchMock);
    const crafted = { studentId: "someone-else", student_id: "someone-else" };

    await getHandwrittenMistakes(crafted as never);
    await getHandwrittenRevisionItems(crafted as never);
    await getHandwrittenWeakAreas();

    for (const call of fetchMock.mock.calls) {
      expect(String(call[0])).not.toContain("student");
    }
  });

  it("treats a missing analytics row (404) as no data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "Analytics not found" }, 404)),
    );

    await expect(getHandwrittenAnalytics("subject-1")).resolves.toBeNull();
  });

  it("does not swallow a 403 on analytics", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: "Students can view only their own learning data" }, 403),
      ),
    );

    const failure = await getHandwrittenAnalytics("subject-1").catch((reason) => reason);

    expect(failure).toBeInstanceOf(ApiRequestError);
    expect(failure.status).toBe(403);
  });

  it("rejects list requests the server refuses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "Learning data not found" }, 404)),
    );

    await expect(getHandwrittenMistakes()).rejects.toBeInstanceOf(ApiRequestError);
  });
});
