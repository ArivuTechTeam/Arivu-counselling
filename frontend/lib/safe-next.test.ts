import { describe, expect, it } from "vitest";

import { safeDashboardNext } from "./safe-next";

describe("safeDashboardNext", () => {
  it("uses the dashboard when no destination is supplied", () => {
    expect(safeDashboardNext(null)).toBe("/dashboard");
    expect(safeDashboardNext("  ")).toBe("/dashboard");
  });

  it("keeps dashboard paths and their query strings", () => {
    expect(safeDashboardNext("/dashboard/student?tab=practice#ignored")).toBe(
      "/dashboard/student?tab=practice",
    );
  });

  it.each([
    "https://example.com/dashboard",
    "//example.com/dashboard",
    "/dashboard.evil",
    "/dashboard\\admin",
    "/dashboard\u0000/admin",
  ])("rejects unsafe destination %s", (destination) => {
    expect(safeDashboardNext(destination)).toBe("/dashboard");
  });
});
