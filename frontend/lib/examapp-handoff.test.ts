import { describe, expect, it } from "vitest";

import { isExamAppHandoffVisible } from "./examapp-handoff";

describe("ExamApp handoff visibility", () => {
  it.each(["student", "teacher", "institution_admin"] as const)(
    "gates %s directly on the dedicated tenant value",
    (role) => {
      expect(isExamAppHandoffVisible(role, false)).toBe(false);
      expect(isExamAppHandoffVisible(role, true)).toBe(true);
    },
  );

  it("always allows a super admin", () => {
    expect(isExamAppHandoffVisible("super_admin", false)).toBe(true);
  });
});
