import { describe, expect, it } from "vitest";

import { buildContentSecurityPolicy } from "./content-security-policy";

describe("content security policy", () => {
  it("allows only nonce-bearing inline scripts in production", () => {
    const policy = buildContentSecurityPolicy({
      nonce: "test-nonce",
      supabaseOrigin: "https://project.supabase.co",
      apiOrigin: "https://api.example.com",
    });

    const scriptDirective = policy
      .split(";")
      .find((directive) => directive.trim().startsWith("script-src"));
    expect(scriptDirective).toContain("'nonce-test-nonce'");
    expect(scriptDirective).toContain("'strict-dynamic'");
    expect(scriptDirective).toContain("'wasm-unsafe-eval'");
    expect(scriptDirective).not.toContain("'unsafe-inline'");
    expect(scriptDirective).not.toContain("'unsafe-eval'");
    expect(policy).toContain("upgrade-insecure-requests");
  });

  it("adds unsafe-eval only for the Next.js development runtime", () => {
    const policy = buildContentSecurityPolicy({
      nonce: "dev-nonce",
      supabaseOrigin: "http://127.0.0.1:54321",
      apiOrigin: "http://127.0.0.1:8001",
      development: true,
    });

    expect(policy).toContain("'unsafe-eval'");
    expect(policy).not.toContain("upgrade-insecure-requests");
  });
});
