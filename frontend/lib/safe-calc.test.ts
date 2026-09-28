import { describe, expect, it } from "vitest";

import { safeCalc } from "./safe-calc";

describe("safeCalc", () => {
  it("evaluates arithmetic with precedence and parentheses", () => {
    expect(safeCalc("2+3*4")).toBe(14);
    expect(safeCalc("(1500*15)/100")).toBe(225);
    expect(safeCalc("10/4")).toBe(2.5);
    expect(safeCalc("(1+2)*(3+4)")).toBe(21);
  });
  it("returns null for malformed input", () => {
    expect(safeCalc("2+")).toBeNull();
    expect(safeCalc("(1+2")).toBeNull();
    expect(safeCalc("1+2)")).toBeNull();
    expect(safeCalc("")).toBeNull();
  });
  it("never executes non-arithmetic input (safety)", () => {
    expect(safeCalc("alert(1)")).toBeNull();
    expect(safeCalc("1;alert(1)")).toBeNull();
    expect(safeCalc("a+b")).toBeNull();
    expect(safeCalc("2**3")).toBeNull();
  });
});
