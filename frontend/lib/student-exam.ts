export type StudentAttemptSource = "quiz" | "practice";

export function isStudentExamPath(pathname: string): boolean {
  return /^\/dashboard\/student\/(attempt|practice)\/[^/]+\/?$/.test(pathname);
}

export function examExitDestination(source: StudentAttemptSource): string {
  return source === "practice" ? "/dashboard/student/practice" : "/dashboard/student";
}

type ExamNavigationWindow = {
  history: Pick<History, "state" | "pushState">;
  location: Pick<Location, "href">;
  addEventListener: (type: "popstate", listener: () => void) => void;
  removeEventListener: (type: "popstate", listener: () => void) => void;
};

/**
 * Put a same-URL history entry behind an active exam. Back reaches that entry
 * first, so the student stays on the exam while we ask whether to end it.
 * Preserve Next's history state; it contains App Router navigation metadata.
 */
export function installExamBackGuard(
  browser: ExamNavigationWindow,
  attemptId: string,
  onBack: () => void,
): () => void {
  const examUrl = browser.location.href;
  const addGuardEntry = () => {
    const previous = browser.history.state;
    const state = previous && typeof previous === "object" ? previous : {};
    browser.history.pushState(
      { ...state, __studentExamGuard: attemptId },
      "",
      examUrl,
    );
  };

  if (browser.history.state?.__studentExamGuard !== attemptId) {
    addGuardEntry();
  }

  const handleBack = () => {
    // popstate has already moved the history pointer. Restore the exam URL
    // before showing the dialog; a cancelled exit must not leave the page.
    addGuardEntry();
    onBack();
  };
  browser.addEventListener("popstate", handleBack);
  return () => browser.removeEventListener("popstate", handleBack);
}
