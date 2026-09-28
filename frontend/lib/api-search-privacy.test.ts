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

import {
  getAdminQuizSets,
  getPublishedQuizMonitor,
  listDocumentLog,
  listStudentQuizzes,
  listUsers,
} from "./api";

type SearchCase = {
  name: string;
  run: () => Promise<unknown>;
  path: string;
};

describe("private search transport", () => {
  beforeEach(() => {
    vi.stubGlobal("window", { setTimeout, clearTimeout });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [], quizzes: [], next_cursor: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each<SearchCase>([
    {
      name: "student quizzes",
      run: () => listStudentQuizzes({ query: "private student term" }),
      path: "/api/v1/quizzes/search",
    },
    {
      name: "document log",
      run: () => listDocumentLog({ query: "private document term" }),
      path: "/api/v1/documents/log/search",
    },
    {
      name: "user directory",
      run: () => listUsers(1, "private user term"),
      path: "/api/v1/users/search",
    },
    {
      name: "published quizzes",
      run: () => getPublishedQuizMonitor({ query: "private teacher term" }),
      path: "/api/v1/teacher/published-quizzes/search",
    },
    {
      name: "admin quiz sets",
      run: () => getAdminQuizSets({ query: "private admin term" }),
      path: "/api/v1/admin/quiz-sets/search",
    },
  ])("sends $name text only in a POST body", async ({ run, path }) => {
    await run();

    const fetchMock = vi.mocked(fetch);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(`http://localhost:8000${path}`);
    expect(String(url)).not.toContain("private");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toMatchObject({
      query: expect.stringContaining("private"),
    });
  });

  it("keeps an empty search on the read-only URL without a q parameter", async () => {
    await listStudentQuizzes({ query: "   ", subjectId: "subject-1" });

    const fetchMock = vi.mocked(fetch);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:8000/api/v1/quizzes?subject_id=subject-1",
    );
    expect(init?.method).toBe("GET");
  });
});
