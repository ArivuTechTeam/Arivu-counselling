"use client";

import useSWR from "swr";
import useSWRInfinite from "swr/infinite";

import {
  BookmarkedQuestion,
  ChallengeInfo,
  DailyInfo,
  ExamConfig,
  Leaderboard,
  MyChallenge,
  RevisionTopic,
  StudentStats,
  WeakAnalysis,
  getChallenge,
  getDaily,
  getHandwrittenAnalytics,
  getHandwrittenMistakes,
  getHandwrittenRevisionItems,
  getHandwrittenWeakAreas,
  HandwrittenMistakeSeverity,
  listStudentEvaluationPapers,
  getExamConfig,
  getLeaderboard,
  getRevisionTopics,
  getStudentStats,
  getWeakAnalysis,
  listBookmarks,
  listMyChallenges,
  listPracticeSubjects,
  listStudentAttempts,
  listStudentQuizzes,
  StudentAttemptFilters,
  StudentQuizFilters,
} from "@/lib/api";

export const STUDENT_QUIZZES_KEY = "student:quiz-catalog";
export const STUDENT_STATS_KEY = "student:stats";
export const STUDENT_ATTEMPTS_KEY = "student:attempts";
export const STUDENT_WEAK_ANALYSIS_KEY = "student:weak-analysis";
export const STUDENT_BOOKMARKS_KEY = "student:bookmarks";
export const STUDENT_REVISION_TOPICS_KEY = "student:revision-topics";
export const STUDENT_DAILY_KEY = "student:daily";
export const STUDENT_EXAM_CONFIG_KEY = "student:exam-config";
export const STUDENT_LEADERBOARD_KEY_PREFIX = "student:leaderboard:";
export const STUDENT_CHALLENGE_KEY_PREFIX = "student:challenge:";
export const STUDENT_MY_CHALLENGES_KEY = "student:my-challenges";
export const STUDENT_PRACTICE_SUBJECTS_KEY = "student:practice-subjects";

/** One shared catalog request for Dashboard, Subjects, Smart Quiz and Challenge. */
export function useStudentQuizzes(filters: Omit<StudentQuizFilters, "cursor"> = {}) {
  const filterKey = JSON.stringify(filters);
  const query = useSWRInfinite(
    (index, previous) => {
      if (index > 0 && !previous?.next_cursor) return null;
      return [STUDENT_QUIZZES_KEY, filterKey, previous?.next_cursor ?? ""] as const;
    },
    ([, , cursor]) => listStudentQuizzes({ ...filters, cursor: cursor || undefined }),
  );
  const pages = query.data;
  return {
    ...query,
    data: pages?.flatMap((page) => page.items),
    hasMore: Boolean(pages?.at(-1)?.next_cursor),
    loadMore: () => query.setSize((size) => size + 1),
    isLoadingMore: Boolean(query.isValidating && pages),
  };
}

/** Enrolled subjects for self-serve practice, independent of published quizzes. */
export function usePracticeSubjects() {
  return useSWR(STUDENT_PRACTICE_SUBJECTS_KEY, listPracticeSubjects);
}

export function useStudentStats() {
  return useSWR<StudentStats>(STUDENT_STATS_KEY, getStudentStats);
}

export function useStudentAttempts(
  enabled = true,
  filters: Omit<StudentAttemptFilters, "cursor"> = {},
) {
  const filterKey = JSON.stringify(filters);
  const query = useSWRInfinite(
    (index, previous) => {
      if (!enabled || (index > 0 && !previous?.next_cursor)) return null;
      return [STUDENT_ATTEMPTS_KEY, filterKey, previous?.next_cursor ?? ""] as const;
    },
    ([, , cursor]) => listStudentAttempts({ ...filters, cursor: cursor || undefined }),
  );
  const pages = query.data;
  return {
    ...query,
    data: pages?.flatMap((page) => page.items),
    hasMore: Boolean(pages?.at(-1)?.next_cursor),
    loadMore: () => query.setSize((size) => size + 1),
    isLoadingMore: Boolean(query.isValidating && pages),
  };
}

export function useStudentWeakAnalysis() {
  return useSWR<WeakAnalysis>(STUDENT_WEAK_ANALYSIS_KEY, getWeakAnalysis);
}

export function useStudentBookmarks() {
  return useSWR<BookmarkedQuestion[]>(STUDENT_BOOKMARKS_KEY, listBookmarks);
}

export function useStudentRevisionTopics() {
  return useSWR<RevisionTopic[]>(STUDENT_REVISION_TOPICS_KEY, getRevisionTopics);
}

export function useStudentDaily() {
  return useSWR<DailyInfo>(STUDENT_DAILY_KEY, getDaily);
}

export function useStudentExamConfig() {
  return useSWR<ExamConfig>(STUDENT_EXAM_CONFIG_KEY, getExamConfig);
}

export function studentLeaderboardKey(courseId?: string) {
  return `${STUDENT_LEADERBOARD_KEY_PREFIX}${courseId ?? "default"}`;
}

export function useStudentLeaderboard(courseId?: string) {
  return useSWR<Leaderboard>(
    studentLeaderboardKey(courseId),
    () => getLeaderboard(courseId),
    { keepPreviousData: true },
  );
}

export function studentChallengeKey(token: string) {
  return `${STUDENT_CHALLENGE_KEY_PREFIX}${token}`;
}

export function useStudentChallenge(token: string) {
  return useSWR<ChallengeInfo>(studentChallengeKey(token), () => getChallenge(token));
}

export function useMyChallenges() {
  return useSWR<MyChallenge[]>(STUDENT_MY_CHALLENGES_KEY, listMyChallenges);
}

// --- Handwritten learning. Keys include every filter so each view caches on its own. ---
export const STUDENT_HW_PAPERS_KEY = "student:handwritten-papers";
export const STUDENT_HW_MISTAKES_KEY = "student:handwritten-mistakes";
export const STUDENT_HW_REVISION_KEY = "student:handwritten-revision";
export const STUDENT_HW_ANALYTICS_KEY = "student:handwritten-analytics";
export const STUDENT_HW_WEAK_AREAS_KEY = "student:handwritten-weak-areas";

/** Papers the student can access; the learning pages derive their subject filter from these. */
export function useStudentHandwrittenPapers() {
  return useSWR(STUDENT_HW_PAPERS_KEY, listStudentEvaluationPapers);
}

export function useStudentHandwrittenMistakes(filters: {
  subjectId?: string;
  severity?: HandwrittenMistakeSeverity;
}) {
  return useSWR(
    [STUDENT_HW_MISTAKES_KEY, filters.subjectId ?? "", filters.severity ?? ""],
    () => getHandwrittenMistakes(filters),
  );
}

export function useStudentHandwrittenRevisionItems(filters: {
  subjectId?: string;
  resolved?: boolean;
}) {
  return useSWR(
    [STUDENT_HW_REVISION_KEY, filters.subjectId ?? "", String(filters.resolved ?? "")],
    () => getHandwrittenRevisionItems(filters),
  );
}

/** Pass null to skip the request (e.g. while the subject list is still loading). */
export function useStudentHandwrittenAnalytics(subjectId: string | null) {
  return useSWR(
    subjectId ? [STUDENT_HW_ANALYTICS_KEY, subjectId] : null,
    () => getHandwrittenAnalytics(subjectId as string),
  );
}

export function useStudentHandwrittenWeakAreas(subjectId?: string) {
  return useSWR([STUDENT_HW_WEAK_AREAS_KEY, subjectId ?? ""], () =>
    getHandwrittenWeakAreas(subjectId),
  );
}
