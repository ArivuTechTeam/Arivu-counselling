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

import { replyToSupportContact, submitSupportContact } from "./api";

describe("role-aware support API", () => {
  beforeEach(() => {
    vi.stubGlobal("window", { setTimeout, clearTimeout });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            reference: "AAAAAAAAAAAA",
            routed_to: "platform",
            status: "open",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("submits only user-editable fields and leaves identity routing to the server", async () => {
    await submitSupportContact({
      kind: "support",
      category: "general_support",
      message: "Please help with this account.",
    });

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toBe("http://localhost:8000/api/v1/contact");
    expect(init?.method).toBe("POST");
    const body = JSON.parse(String(init?.body));
    expect(body).toEqual({
      kind: "support",
      category: "general_support",
      message: "Please help with this account.",
    });
    expect(body).not.toHaveProperty("requester_role");
    expect(body).not.toHaveProperty("tenant_id");
    expect(body).not.toHaveProperty("routed_to");
  });

  it("lets support staff answer and close a request", async () => {
    await replyToSupportContact("AAAAAAAAAAAA", "This is resolved.", "closed");

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toBe(
      "http://localhost:8000/api/v1/contact/inbox/AAAAAAAAAAAA/reply",
    );
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      reply: "This is resolved.",
      status: "closed",
    });
  });
});
