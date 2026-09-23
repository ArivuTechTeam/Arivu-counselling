import { describe, expect, it } from "vitest";

import {
  DEFAULT_INSTITUTION_COLOR,
  institutionThemeStyle,
  normalizeInstitutionColor,
} from "./institution-theme";

describe("institution theme", () => {
  it("normalizes valid tenant colors and rejects unsafe values", () => {
    expect(normalizeInstitutionColor("#7c3aed")).toBe("#7C3AED");
    expect(normalizeInstitutionColor("red; background:url(example)")).toBe(
      DEFAULT_INSTITUTION_COLOR,
    );
  });

  it("derives scoped semantic and sidebar tokens", () => {
    const style = institutionThemeStyle("#7C3AED");
    expect(style["--tenant-primary"]).toBe("#7C3AED");
    expect(style["--tenant-sidebar-start"]).toMatch(/^#[0-9A-F]{6}$/);
    expect(style["--primary"]).toMatch(/^\d+ \d+% \d+%$/);
    expect(style["--background"]).toMatch(/^\d+ \d+% 96%$/);
  });

  it("uses readable dark text for a very light selected color", () => {
    const style = institutionThemeStyle("#FFFF00");
    expect(style["--tenant-on-primary"]).toBe("#13231A");
    expect(style["--primary-foreground"]).toBe("156 22% 9%");
  });
});
