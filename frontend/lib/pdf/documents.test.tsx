import { describe, expect, it } from "vitest";

import { resolvedPdfBranding } from "./branding";

describe("tenant PDF branding", () => {
  it("keeps each tenant's name, logo, and color separate", () => {
    const alpha = resolvedPdfBranding({
      name: "Alpha College",
      logo_url: "https://example.test/alpha.png",
      primary_color: "#112233",
    });
    const beta = resolvedPdfBranding({
      name: "Beta Institute",
      logo_url: "https://example.test/beta.png",
      primary_color: "#AABBCC",
    });

    expect(alpha).toEqual({
      name: "Alpha College",
      logo_url: "https://example.test/alpha.png",
      primary_color: "#112233",
    });
    expect(beta).toEqual({
      name: "Beta Institute",
      logo_url: "https://example.test/beta.png",
      primary_color: "#AABBCC",
    });
    expect(alpha).not.toEqual(beta);
  });
});
