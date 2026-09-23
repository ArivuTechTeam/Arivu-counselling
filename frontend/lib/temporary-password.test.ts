import { describe, expect, it } from "vitest";

import {
  generateTemporaryPassword,
  validTemporaryPassword,
} from "./temporary-password";

describe("temporary password helpers", () => {
  it("generates passwords accepted by the password policy", () => {
    for (let index = 0; index < 25; index += 1) {
      const password = generateTemporaryPassword();
      expect(password).toHaveLength(14);
      expect(validTemporaryPassword(password)).toBe(true);
    }
  });

  it.each([
    "TooShort1",
    "alllowercase123",
    "ALLUPPERCASE123",
    "NoNumbersHere",
  ])("rejects invalid password %s", (password) => {
    expect(validTemporaryPassword(password)).toBe(false);
  });
});
