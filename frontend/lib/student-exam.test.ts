import { describe, expect, it, vi } from "vitest";

import {
  examExitDestination,
  installExamBackGuard,
  isStudentExamPath,
} from "./student-exam";

describe("focused student exam routing", () => {
  it("only uses the exam shell for an individual attempt", () => {
    expect(isStudentExamPath("/dashboard/student/attempt/abc")).toBe(true);
    expect(isStudentExamPath("/dashboard/student/practice/abc")).toBe(true);
    expect(isStudentExamPath("/dashboard/student/practice")).toBe(false);
    expect(isStudentExamPath("/dashboard/teacher/attempt/abc")).toBe(false);
  });

  it("returns each attempt type to its own student area", () => {
    expect(examExitDestination("quiz")).toBe("/dashboard/student");
    expect(examExitDestination("practice")).toBe("/dashboard/student/practice");
  });
});

describe("exam browser Back guard", () => {
  function browserWithHistory(initialState: Record<string, unknown> = {}) {
    let state = initialState;
    let popstate: (() => void) | undefined;
    const pushState = vi.fn((next: Record<string, unknown>) => {
      state = next;
    });
    const browser = {
      history: { get state() { return state; }, pushState },
      location: { href: "https://app.example.com/dashboard/student/attempt/a1" },
      addEventListener: vi.fn((_type: "popstate", listener: () => void) => {
        popstate = listener;
      }),
      removeEventListener: vi.fn(),
    };
    return { browser, pushState, back: () => popstate?.() };
  }

  it("keeps the exam URL active and asks before leaving", () => {
    const { browser, pushState, back } = browserWithHistory({ __NA: true });
    const onBack = vi.fn();
    const cleanup = installExamBackGuard(browser, "a1", onBack);

    expect(pushState).toHaveBeenCalledWith(
      { __NA: true, __studentExamGuard: "a1" },
      "",
      browser.location.href,
    );
    back();
    expect(pushState).toHaveBeenCalledTimes(2);
    expect(onBack).toHaveBeenCalledOnce();
    cleanup();
    expect(browser.removeEventListener).toHaveBeenCalledOnce();
  });

  it("does not stack duplicate guard entries after a refresh", () => {
    const { browser, pushState } = browserWithHistory({ __studentExamGuard: "a1" });
    installExamBackGuard(browser, "a1", vi.fn());
    expect(pushState).not.toHaveBeenCalled();
  });
});
