"use client";

import useSWR from "swr";

import {
  getAdminQuizSets,
  getAiMonitoring,
  getClassMonitor,
  getInstitutionAnalytics,
  getPlatformOverview,
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
  return useSWR(STAFF_QUERY_KEYS.institutionQuizSets, () => getAdminQuizSets());
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

export function useTeacherSubjectMetrics() {
  return useSWR(STAFF_QUERY_KEYS.teacherSubjectMetrics, listSubjectMetrics);
}

export function useTeacherQuizSets() {
  return useSWR(STAFF_QUERY_KEYS.teacherQuizSets, listQuizSets);
}

export function useTeacherDocumentLog() {
  return useSWR(STAFF_QUERY_KEYS.teacherDocumentLog, listDocumentLog);
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

export function useInstitutionUsers() {
  return useSWR(STAFF_QUERY_KEYS.institutionUsers, listUsers);
}
