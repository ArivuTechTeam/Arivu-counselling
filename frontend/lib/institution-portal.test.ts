import { describe, expect, it } from "vitest";

import {
  institutionLoginPath,
  institutionLoginUrl,
  institutionSignupPath,
  institutionSlugFromPath,
  normalizeInstitutionSlug,
} from "./institution-portal";

describe("institution portal links", () => {
  it("normalizes a valid institution slug", () => {
    expect(normalizeInstitutionSlug(" Alliance-University ")).toBe(
      "alliance-university",
    );
  });

  it.each(["../alliance", "alliance university", "alliance?next=bad", ""])(
    "rejects invalid slug %s",
    (slug) => expect(normalizeInstitutionSlug(slug)).toBe(""),
  );

  it("builds one shared institution entry URL", () => {
    expect(institutionLoginPath("alliance")).toBe("/login/alliance");
    expect(
      institutionLoginUrl("alliance", "https://quiz.example.com/dashboard"),
    ).toBe("https://quiz.example.com/login/alliance");
  });

  it("keeps student registration under the institution slug", () => {
    expect(institutionSignupPath("alliance")).toBe("/signup/alliance");
    expect(institutionSignupPath("alliance", "/dashboard/student/subjects")).toBe(
      "/signup/alliance?next=%2Fdashboard%2Fstudent%2Fsubjects",
    );
  });

  it("reads slugs only from the expected auth path", () => {
    expect(institutionSlugFromPath("/login/alliance", "/login/")).toBe(
      "alliance",
    );
    expect(institutionSlugFromPath("/signup/alliance", "/signup/")).toBe(
      "alliance",
    );
    expect(institutionSlugFromPath("/dashboard", "/login/")).toBe("");
  });
});
