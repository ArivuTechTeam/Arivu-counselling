"use client";

import useSWR from "swr";
import useSWRInfinite from "swr/infinite";

import {
  getAdminQuizSets,
  getAiMonitoring,
  getClassMonitor,
  getInstitutionAnalytics,
  getPlatformOverview,
  getPublishedQuizMonitor,
  getQuestionBank,
  getTeacherAnalytics,
  getTeacherClassOverview,
  listAdmins,
  listCourses,
  listDocumentLog,
  listQuizSets,
  listUsers,
  listSubjectMetrics,
  listTenants,
  DocumentLogFilters,
  PublishedQuizFilters,
} from "@/lib/api";

// Stable, role-scoped keys let pages reuse fresh data when users navigate back
// instead of rebuilding the same dashboard request from zero.
export const STAFF_QUERY_KEYS = {
  institutionAnalytics: "staff:institution:analytics",
  institutionQuizSets: "staff:institution:quiz-sets",
  institutionTeacherAnalytics: "staff:institution:teacher-analytics",
  courses: "staff:courses",
  teacherOverview: "staff:teacher:class-overview",
  teacherMonitor: "staff:teacher:class-monitor",
  teacherPublishedQuizzes: "staff:teacher:published-quizzes",
  teacherSubjectMetrics: "staff:teacher:subject-metrics",
  teacherQuizSets: "staff:teacher:quiz-sets",
  teacherDocumentLog: "staff:teacher:document-log",
  platformOverview: "staff:platform:overview",
  platformAiMonitoring: "staff:platform:ai-monitoring",
  platformQuestionBank: "staff:platform:question-bank",
  institutionUsers: "staff:institution:users",
  platformTenants: "staff:platform:tenants",
  platformAdmins: "staff:platform:admins",
} as const;

export function useInstitutionAnalytics() {
  return useSWR(STAFF_QUERY_KEYS.institutionAnalytics, getInstitutionAnalytics);
}

export function useInstitutionQuizSets() {
  const query = useSWRInfinite(
    (index, previous) => {
      if (index > 0 && !previous?.next_cursor) return null;
      return [STAFF_QUERY_KEYS.institutionQuizSets, previous?.next_cursor ?? ""] as const;
    },
    ([, cursor]) => getAdminQuizSets({ cursor: cursor || undefined }),
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

export function useInstitutionTeacherAnalytics() {
  return useSWR(
    STAFF_QUERY_KEYS.institutionTeacherAnalytics,
    getTeacherAnalytics,
  );
}

export function useCourses() {
  return useSWR(STAFF_QUERY_KEYS.courses, listCourses);
}

export function useTeacherOverview() {
  return useSWR(STAFF_QUERY_KEYS.teacherOverview, getTeacherClassOverview);
}

export function useTeacherMonitor() {
  return useSWR(STAFF_QUERY_KEYS.teacherMonitor, getClassMonitor);
}

export function useTeacherPublishedQuizzes(filters: Omit<PublishedQuizFilters, "cursor"> = {}) {
  const filterKey = JSON.stringify(filters);
  const query = useSWRInfinite(
    (index, previous) => {
      if (index > 0 && !previous?.next_cursor) return null;
      return [STAFF_QUERY_KEYS.teacherPublishedQuizzes, filterKey, previous?.next_cursor ?? ""] as const;
    },
    ([, , cursor]) => getPublishedQuizMonitor({ ...filters, cursor: cursor || undefined }),
  );
  const pages = query.data;
  return {
    ...query,
    data: pages ? { quizzes: pages.flatMap((page) => page.quizzes), next_cursor: pages.at(-1)?.next_cursor ?? null } : undefined,
    hasMore: Boolean(pages?.at(-1)?.next_cursor),
    loadMore: () => query.setSize((size) => size + 1),
    isLoadingMore: Boolean(query.isValidating && pages),
  };
}

export function useTeacherSubjectMetrics() {
  return useSWR(STAFF_QUERY_KEYS.teacherSubjectMetrics, listSubjectMetrics);
}

export function useTeacherQuizSets(archived = false) {
  const rootKey = archived ? `${STAFF_QUERY_KEYS.teacherQuizSets}:archived` : STAFF_QUERY_KEYS.teacherQuizSets;
  const query = useSWRInfinite(
    (index, previous) => {
      if (index > 0 && !previous?.next_cursor) return null;
      return [rootKey, previous?.next_cursor ?? ""] as const;
    },
    ([, cursor]) => listQuizSets(archived, cursor || undefined),
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

export function useTeacherDocumentLog(filters: Omit<DocumentLogFilters, "cursor"> = {}) {
  const filterKey = JSON.stringify(filters);
  const query = useSWRInfinite(
    (index, previous) => {
      if (index > 0 && !previous?.next_cursor) return null;
      return [STAFF_QUERY_KEYS.teacherDocumentLog, filterKey, previous?.next_cursor ?? ""] as const;
    },
    ([, , cursor]) => listDocumentLog({ ...filters, cursor: cursor || undefined }),
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

export function usePlatformOverview() {
  return useSWR(STAFF_QUERY_KEYS.platformOverview, getPlatformOverview);
}

export function usePlatformAiMonitoring() {
  return useSWR(STAFF_QUERY_KEYS.platformAiMonitoring, getAiMonitoring);
}

export function usePlatformQuestionBank() {
  return useSWR(STAFF_QUERY_KEYS.platformQuestionBank, getQuestionBank);
}

export function usePlatformTenants() {
  return useSWR(STAFF_QUERY_KEYS.platformTenants, listTenants);
}

export function usePlatformAdmins() {
  return useSWR(STAFF_QUERY_KEYS.platformAdmins, listAdmins);
}

export function useInstitutionUsers(page = 1, query = "") {
  return useSWR(
    [STAFF_QUERY_KEYS.institutionUsers, page, query],
    () => listUsers(page, query),
  );
}
