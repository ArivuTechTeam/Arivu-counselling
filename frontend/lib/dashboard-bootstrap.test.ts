import { describe, expect, it } from "vitest";

import { dashboardContentState } from "./dashboard-bootstrap";

describe("dashboard role verification", () => {
  it("does not show role pages before the backend verifies the profile", () => {
    expect(dashboardContentState(false, null, true, "/dashboard/teacher")).toBe("loading");
  });

  it("shows a retryable error even if an old role would match the path", () => {
    expect(dashboardContentState(false, "Profile request failed", true, "/dashboard/teacher")).toBe("error");
  });

  it("shows a role page only after verification and a matching path", () => {
    expect(dashboardContentState(true, null, true, "/dashboard/student")).toBe("content");
    expect(dashboardContentState(true, null, false, "/dashboard/teacher")).toBe("loading");
  });
});
