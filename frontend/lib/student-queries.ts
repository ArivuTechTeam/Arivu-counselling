"use client";

import useSWR from "swr";

import { StudentQuiz, listStudentQuizzes } from "@/lib/api";

export const STUDENT_QUIZZES_KEY = "student:quiz-catalog";
export const STUDENT_DASHBOARD_KEY = "dashboard:student";

/** One shared catalog request for Dashboard, Subjects, Smart Quiz and Challenge. */
export function useStudentQuizzes() {
  return useSWR<StudentQuiz[]>(STUDENT_QUIZZES_KEY, listStudentQuizzes);
}
