import { describe, expect, it, vi } from "vitest";

// The shell imports browser-only modules; none of them run for the nav filter.
vi.mock("@/lib/public-env", () => ({ PUBLIC_ENV: { apiBaseUrl: "http://localhost:8000" } }));
vi.mock("@/lib/supabase", () => ({ createClient: () => ({}) }));
vi.mock("next/image", () => ({ default: () => null }));
vi.mock("next/link", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: () => undefined, replace: () => undefined }),
}));

import type { DashboardProfile } from "@/lib/api";
import { groupBySection, visibleNavItems } from "./dashboard-shell";

const FEATURES = {
  faculty_jobs: true,
  quiz_reuse: true,
  batches: true,
  scoring_policies: true,
  commerce_pack: true,
  figure_attach: true,
  paper_bank: true,
} as DashboardProfile["features"];

const NEW_ENTRIES = [
  { label: "Mistake Library", href: "/dashboard/student/handwritten-evaluation/mistakes" },
  { label: "Handwritten Revision", href: "/dashboard/student/handwritten-evaluation/revision" },
  { label: "My Progress", href: "/dashboard/student/handwritten-evaluation/progress" },
];

const labels = (role: string | null, evaluationEnabled: boolean) =>
  visibleNavItems(role, FEATURES, evaluationEnabled).map((item) => item.label);

describe("handwritten learning nav entries", () => {
  it("are hidden for a student whose tenant has handwritten evaluation off", () => {
    const visible = labels("student", false);

    for (const entry of NEW_ENTRIES) expect(visible).not.toContain(entry.label);
  });

  it("are shown, with the right links, when handwritten evaluation is on", () => {
    const items = visibleNavItems("student", FEATURES, true);

    for (const entry of NEW_ENTRIES) {
      expect(items.find((item) => item.label === entry.label)?.href).toBe(entry.href);
    }
  });

  it("sit together, in order, in their own Handwritten Evaluation section", () => {
    const groups = groupBySection(visibleNavItems("student", FEATURES, true));
    const section = groups.filter((group) => group.section === "Handwritten Evaluation");

    // One contiguous group, not several fragments.
    expect(section).toHaveLength(1);
    expect(section[0].items.map((item) => item.label)).toEqual([
      "Exam Papers",
      "My Submissions",
      "Mistake Library",
      "Handwritten Revision",
      "My Progress",
    ]);
  });

  it("are kept out of the quiz Practice section", () => {
    const groups = groupBySection(visibleNavItems("student", FEATURES, true));
    const practice = groups.find((group) => group.section === "Practice");
    const practiceLabels = practice?.items.map((item) => item.label) ?? [];

    // The quiz "Revision" stays in Practice; "Handwritten Revision" does not.
    expect(practiceLabels).toContain("Revision");
    expect(practiceLabels).not.toContain("Handwritten Revision");
    for (const label of ["Exam Papers", "My Submissions", ...NEW_ENTRIES.map((e) => e.label)]) {
      expect(practiceLabels).not.toContain(label);
    }
  });

  it("put a section boundary between the quiz and handwritten Revision entries", () => {
    const sections = groupBySection(visibleNavItems("student", FEATURES, true));
    const sectionOf = (label: string) =>
      sections.find((group) => group.items.some((item) => item.label === label))?.section;

    expect(sectionOf("Revision")).toBe("Practice");
    expect(sectionOf("Handwritten Revision")).toBe("Handwritten Evaluation");
  });

  it("do not leave the section header behind when the flag is off", () => {
    const groups = groupBySection(visibleNavItems("student", FEATURES, false));

    expect(groups.map((group) => group.section)).not.toContain("Handwritten Evaluation");
    // The quiz sections are unaffected.
    expect(groups.map((group) => group.section)).toEqual(
      expect.arrayContaining(["Overview", "Practice", "Progress", "Account"]),
    );
  });

  // Guards future entries too: anything routed into handwritten evaluation must
  // carry the flag, otherwise tenants with the feature off would see a dead link.
  it("leave no handwritten evaluation link visible when the flag is off", () => {
    const leaked = visibleNavItems("student", FEATURES, false).filter((item) =>
      item.href?.includes("/handwritten-evaluation"),
    );

    expect(leaked).toEqual([]);
  });

  it("do not affect the rest of the student nav when the flag is off", () => {
    const visible = labels("student", false);

    expect(visible).toContain("Leaderboard");
  });

  it.each(["teacher", "institution_admin", "super_admin", null])(
    "are never shown to %s, even with the flag on",
    (role) => {
      const visible = labels(role, true);

      for (const entry of NEW_ENTRIES) expect(visible).not.toContain(entry.label);
    },
  );
});
