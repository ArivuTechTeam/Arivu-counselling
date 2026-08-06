import { createClient } from "@/lib/supabase";

// Base URL of the FastAPI backend (from .env.local).
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL!;

/**
 * Build the Authorization header for backend calls.
 *
 * The backend verifies this JWT (the same token Supabase issued at login). We
 * read it from the current browser session and pass it as a Bearer token.
 */
async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export type DocumentOut = {
  id: string;
  original_filename: string | null;
  file_type: string | null;
  status: string;
  created_at: string;
};

export type UploadResult = {
  document: DocumentOut;
  text_preview: string;
  char_count: number;
  truncated: boolean;
};

/** Upload a PDF/DOCX to the backend, which stores + extracts it. */
export async function uploadDocument(file: File): Promise<UploadResult> {
  const headers = await authHeader();
  const form = new FormData();
  form.append("file", file);

  // NOTE: don't set Content-Type manually — the browser sets the correct
  // multipart boundary automatically when the body is a FormData.
  const res = await fetch(`${API_BASE}/api/v1/documents/upload`, {
    method: "POST",
    headers,
    body: form,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Upload failed (${res.status})`);
  }
  return res.json();
}

/** List the documents uploaded within the caller's tenant. */
export async function listDocuments(): Promise<DocumentOut[]> {
  const headers = await authHeader();
  const res = await fetch(`${API_BASE}/api/v1/documents`, { headers });
  if (!res.ok) {
    throw new Error(`Failed to load documents (${res.status})`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Quiz generation (Slice 3)
// ---------------------------------------------------------------------------

export type GeneratedQuestion = {
  id?: string;
  type: string;
  question_text: string;
  options?: { id: string; text: string }[] | null;
  // Shape varies by type: string | string[] | {value,tolerance} | {answers}
  correct_answer: unknown;
  explanation?: string | null;
  difficulty?: string;
  marks?: number;
};

export type GenerateResponse = {
  quiz_set_id: string;
  variant_id: string;
  provider: string;
  questions: GeneratedQuestion[];
};

export type GenerateRequest = {
  document_id: string;
  num_questions: number;
  question_types: string[];
  cognitive_level: string;
  difficulty: string;
  subject_id?: string;
};

/** Ask the backend to generate a quiz from a document. Can take 20-40s. */
export async function generateQuiz(
  req: GenerateRequest,
): Promise<GenerateResponse> {
  const headers = {
    ...(await authHeader()),
    "Content-Type": "application/json",
  };
  const res = await fetch(`${API_BASE}/api/v1/quiz-sets/generate`, {
    method: "POST",
    headers,
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Generation failed (${res.status})`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Teacher review (Slice 4)
// ---------------------------------------------------------------------------

export type QuizSetSummary = {
  id: string;
  title: string;
  status: string;
  created_at: string;
  published_at?: string | null;
};

export type ReviewQuestion = {
  id: string;
  type: string;
  question_text: string;
  options?: { id: string; text: string }[] | null;
  correct_answer: unknown;
  explanation?: string | null;
  difficulty?: string;
  marks?: number;
  review_status: string;
};

export type QuizSetDetail = QuizSetSummary & {
  variants: {
    id: string;
    variant_type: string;
    total_marks?: number | null;
    questions: ReviewQuestion[];
  }[];
};

/** Fields a teacher may edit on a question (all optional). */
export type QuestionPatch = Partial<
  Pick<
    ReviewQuestion,
    "question_text" | "options" | "correct_answer" | "explanation" | "difficulty" | "marks"
  >
>;

async function jsonRequest<T>(
  path: string,
  method: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { ...(await authHeader()) };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    throw new Error(b.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export const listQuizSets = () =>
  jsonRequest<QuizSetSummary[]>("/api/v1/quiz-sets", "GET");

export const getQuizSet = (id: string) =>
  jsonRequest<QuizSetDetail>(`/api/v1/quiz-sets/${id}`, "GET");

export const editQuestion = (id: string, patch: QuestionPatch) =>
  jsonRequest<ReviewQuestion>(`/api/v1/questions/${id}`, "PATCH", patch);

export const approveQuestion = (id: string) =>
  jsonRequest<ReviewQuestion>(`/api/v1/questions/${id}/approve`, "POST");

export const rejectQuestion = (id: string) =>
  jsonRequest<ReviewQuestion>(`/api/v1/questions/${id}/reject`, "POST");

/** AI rewrites the question (same type/concept). Can take ~10-20s. */
export const regenerateQuestion = (id: string) =>
  jsonRequest<ReviewQuestion>(`/api/v1/questions/${id}/regenerate`, "POST");

export const publishQuizSet = (id: string) =>
  jsonRequest<QuizSetSummary>(`/api/v1/quiz-sets/${id}/publish`, "POST");

// ---------------------------------------------------------------------------
// Student quiz-taking (Slice 5)
// ---------------------------------------------------------------------------

export type StudentVariant = {
  id: string;
  variant_type: string;
  total_marks?: number | null;
  time_limit_minutes?: number | null;
  question_count: number;
};

export type StudentQuiz = {
  id: string;
  title: string;
  published_at?: string | null;
  variants: StudentVariant[];
};

/** A question as shown to a student while TAKING (no answers). */
export type TakingQuestion = {
  id: string;
  type: string;
  question_text: string;
  options?: { id: string; text: string }[] | null;
  marks?: number;
};

/** A question after grading (answers revealed). */
export type ResultQuestion = TakingQuestion & {
  correct_answer: unknown;
  explanation?: string | null;
  student_answer: unknown;
  is_correct: boolean | null;
  marks_awarded: number | null;
};

export type AttemptInProgress = {
  attempt_id: string;
  status: "in_progress";
  questions: TakingQuestion[];
};

export type AttemptResult = {
  attempt_id: string;
  status: string; // "graded"
  total_score: number;
  max_score: number;
  results: ResultQuestion[];
};

export type AttemptState = AttemptInProgress | AttemptResult;

export const listStudentQuizzes = () =>
  jsonRequest<StudentQuiz[]>("/api/v1/quizzes", "GET");

export const startAttempt = (variantId: string) =>
  jsonRequest<{ attempt_id: string }>("/api/v1/attempts", "POST", {
    variant_id: variantId,
  });

export const getAttempt = (attemptId: string) =>
  jsonRequest<AttemptState>(`/api/v1/attempts/${attemptId}`, "GET");

export const submitAttempt = (
  attemptId: string,
  answers: { question_id: string; student_answer: unknown }[],
) =>
  jsonRequest<AttemptResult>(`/api/v1/attempts/${attemptId}/submit`, "POST", {
    answers,
  });

// ---------------------------------------------------------------------------
// Academics (courses / subjects) — for the teacher's quiz targeting
// ---------------------------------------------------------------------------

export type Subject = { id: string; name: string };
export type Course = { id: string; name: string; subjects: Subject[] };

export const listCourses = () => jsonRequest<Course[]>("/api/v1/courses", "GET");

/** Public (no-auth) course list for the signup dropdown. */
export async function listPublicCourses(
  tenantId: string,
): Promise<{ id: string; name: string }[]> {
  const res = await fetch(
    `${API_BASE}/api/v1/public/courses?tenant_id=${encodeURIComponent(tenantId)}`,
  );
  if (!res.ok) throw new Error(`Failed to load courses (${res.status})`);
  return res.json();
}

// --- Admin: manage courses & subjects ---
export const createCourse = (name: string) =>
  jsonRequest<Course>("/api/v1/courses", "POST", { name });

export const createSubject = (courseId: string, name: string) =>
  jsonRequest<Subject>("/api/v1/subjects", "POST", { course_id: courseId, name });

export const deleteCourse = (id: string) =>
  jsonRequest<{ deleted: string }>(`/api/v1/courses/${id}`, "DELETE");

export const deleteSubject = (id: string) =>
  jsonRequest<{ deleted: string }>(`/api/v1/subjects/${id}`, "DELETE");

// ---------------------------------------------------------------------------
// Admin: users + analytics
// ---------------------------------------------------------------------------

export type AdminUser = {
  id: string;
  full_name: string | null;
  role: string;
  email: string | null;
  courses: string[];
};

export type UserCreateInput = {
  full_name: string;
  email: string;
  password: string;
  role: "teacher" | "student";
  course_id?: string;
};

export type AdminStats = {
  teachers: number;
  students: number;
  courses: number;
  subjects: number;
  quiz_sets: number;
  published_quizzes: number;
};

export type PlatformStats = {
  institutions: number;
  total_teachers: number;
  total_students: number;
  per_institution: { id: string; name: string; teachers: number; students: number }[];
};

export const listUsers = () => jsonRequest<AdminUser[]>("/api/v1/users", "GET");
export const createUser = (input: UserCreateInput) =>
  jsonRequest<{ id: string; email: string }>("/api/v1/users", "POST", input);
export const deleteUser = (id: string) =>
  jsonRequest<{ deleted: string }>(`/api/v1/users/${id}`, "DELETE");
export const getAdminStats = () =>
  jsonRequest<AdminStats>("/api/v1/admin/stats", "GET");
export const getPlatformStats = () =>
  jsonRequest<PlatformStats>("/api/v1/platform/stats", "GET");
