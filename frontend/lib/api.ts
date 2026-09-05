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
    throw new Error(
      body.detail || "We couldn't upload your file. Please try again.",
    );
  }
  return res.json();
}

/** List the documents uploaded within the caller's tenant. */
export async function listDocuments(): Promise<DocumentOut[]> {
  const headers = await authHeader();
  const res = await fetch(`${API_BASE}/api/v1/documents`, { headers });
  if (!res.ok) {
    throw new Error("We couldn't load your documents. Please try again.");
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
    throw new Error(
      body.detail ||
        "We couldn't generate the quiz. Please try again — if it keeps failing, contact support.",
    );
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
    throw new Error(
      b.detail || "Something went wrong. Please try again.",
    );
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

// AI Tutor — cached, deeper explanation + a simplified version + hints.
export type Explanation = {
  explanation: string;
  simplified: string;
  hints: string[];
  cached: boolean;
};

export const explainQuestion = (id: string) =>
  jsonRequest<Explanation>(`/api/v1/questions/${id}/explain`, "POST");

export const publishQuizSet = (id: string) =>
  jsonRequest<QuizSetSummary>(`/api/v1/quiz-sets/${id}/publish`, "POST");

/** Approve every still-pending question in the set in one call. */
export const approveAllQuestions = (id: string) =>
  jsonRequest<{ approved: number }>(`/api/v1/quiz-sets/${id}/approve-all`, "POST");

// ---------------------------------------------------------------------------
// Student quiz-taking (Slice 5)
// ---------------------------------------------------------------------------

export type StudentVariant = {
  id: string;
  variant_type: string;
  total_marks?: number | null;
  time_limit_minutes?: number | null;
  question_count: number;
  attempted: boolean;
  attempt_count: number;
  best_pct?: number | null;
};

export type StudentQuiz = {
  id: string;
  title: string;
  published_at?: string | null;
  subject_id?: string | null;
  subject_name?: string | null;
  chapter_name?: string | null;
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
  time_limit_minutes?: number | null; // set for timed modes (exam)
  started_at?: string | null;
};

export type AttemptResult = {
  attempt_id: string;
  status: string; // "graded"
  quiz_title?: string;
  total_score: number;
  max_score: number;
  challenge_token?: string | null; // present when the session belongs to a challenge
  results: ResultQuestion[];
};

export type AttemptState = AttemptInProgress | AttemptResult;

export const listStudentQuizzes = () =>
  jsonRequest<StudentQuiz[]>("/api/v1/quizzes", "GET");

export type WeakArea = { topic: string; accuracy: number; attempted: number };
export type StudentStats = {
  quizzes_taken: number;
  questions_solved: number;
  overall_accuracy: number;
  weak_areas: WeakArea[];
  topic_accuracy: WeakArea[];
};

// --- Hierarchical weak-area analysis (Subject -> Chapter -> Topic) ---
export type WeakTopicNode = { topic: string; accuracy: number; answered: number };
export type WeakChapterNode = {
  chapter: string;
  accuracy: number;
  answered: number;
  topics: WeakTopicNode[];
};
export type WeakSubjectNode = {
  subject: string;
  accuracy: number;
  answered: number;
  chapters: WeakChapterNode[];
};
export type WeakAnalysis = {
  overall: {
    accuracy: number;
    answered: number;
    correct: number;
    weak_topics: number;
  };
  subjects: WeakSubjectNode[];
};

/** Subject -> Chapter -> Topic success-rate breakdown, weakest first. */
export const getWeakAnalysis = () =>
  jsonRequest<WeakAnalysis>("/api/v1/student/weak-analysis", "GET");

// --- Weak topics to revise (revision list, topic side) ---
export type RevisionTopic = {
  key: string;
  subject: string;
  chapter: string;
  topic: string;
  accuracy: number;
  answered: number;
};
export const getRevisionTopics = () =>
  jsonRequest<RevisionTopic[]>("/api/v1/student/revision-topics", "GET");
export const markTopicRevised = (key: string) =>
  jsonRequest<{ revised: string }>(
    "/api/v1/student/revision-topics/revised",
    "POST",
    { key },
  );

/** Read-only overview for the student dashboard (real metrics). */
export const getStudentStats = () =>
  jsonRequest<StudentStats>("/api/v1/student/stats", "GET");

export type AttemptHistoryItem = {
  attempt_id: string;
  quiz_title: string;
  variant_type: string | null;
  total_score: number | null;
  max_score: number | null;
  submitted_at: string | null;
};

/** The student's past graded attempts, newest first. */
export const listStudentAttempts = () =>
  jsonRequest<AttemptHistoryItem[]>("/api/v1/student/attempts", "GET");

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

// --- Self-serve practice (Smart Quiz, chapter practice, …) ---
// These mirror the quiz-attempt shape so the same take/results UI is reused.
export type StartPracticeInput = {
  mode?: string;
  subject_id?: string | null;
  chapter_id?: string | null;
  count?: number;
  difficulty?: string | null;
};
export const startPracticeSession = (input: StartPracticeInput) =>
  jsonRequest<{ session_id: string }>("/api/v1/practice/sessions", "POST", input);
export const getPracticeSession = (id: string) =>
  jsonRequest<AttemptState>(`/api/v1/practice/sessions/${id}`, "GET");
export const submitPracticeSession = (
  id: string,
  answers: { question_id: string; student_answer: unknown }[],
) =>
  jsonRequest<AttemptResult>(`/api/v1/practice/sessions/${id}/submit`, "POST", {
    answers,
  });

// --- Revision list (bookmarks) ---
export type BookmarkedQuestion = {
  id: string;
  type: string;
  question_text: string;
  options?: { id: string; text: string }[] | null;
  correct_answer: unknown;
  explanation?: string | null;
  difficulty?: string | null;
};
export const listBookmarks = () =>
  jsonRequest<BookmarkedQuestion[]>("/api/v1/bookmarks", "GET");
export const addBookmark = (questionId: string) =>
  jsonRequest<{ bookmarked: string }>("/api/v1/bookmarks", "POST", {
    question_id: questionId,
  });
export const removeBookmark = (questionId: string) =>
  jsonRequest<{ removed: string }>(`/api/v1/bookmarks/${questionId}`, "DELETE");

// --- Challenge a friend (same institution) ---
export type ChallengeLeaderRow = {
  name: string;
  pct: number;
  is_creator: boolean;
  is_you: boolean;
};
export type ChallengeInfo = {
  token: string;
  creator_name: string;
  questions: number;
  is_creator: boolean;
  my_status: "not_taken" | "in_progress" | "done";
  my_session_id: string | null;
  my_pct: number | null;
  leaderboard: ChallengeLeaderRow[];
};
export const createChallenge = (input: {
  subject_id?: string | null;
  count?: number;
}) =>
  jsonRequest<{ token: string; session_id: string }>(
    "/api/v1/challenges",
    "POST",
    input,
  );
export const getChallenge = (token: string) =>
  jsonRequest<ChallengeInfo>(`/api/v1/challenges/${token}`, "GET");
export const acceptChallenge = (token: string) =>
  jsonRequest<{ session_id: string }>(
    `/api/v1/challenges/${token}/accept`,
    "POST",
    {},
  );

// --- Daily challenge + streak ---
export type DailyInfo = {
  done_today: boolean;
  streak: number;
  longest: number;
  today_session_id: string | null;
  last7: { date: string; done: boolean }[];
};
export const getDaily = () => jsonRequest<DailyInfo>("/api/v1/daily", "GET");
export const startDaily = () =>
  jsonRequest<{ session_id: string }>("/api/v1/daily/start", "POST", {});

// --- Exam Simulator (timed, negative marking, per-institution pattern) ---
export type ExamConfig = {
  questions: number;
  duration_minutes: number;
  negative_marking: number;
};
export const getExamConfig = () =>
  jsonRequest<ExamConfig>("/api/v1/exam/config", "GET");
export const startExam = () =>
  jsonRequest<{ session_id: string; questions: number; duration_minutes: number }>(
    "/api/v1/exam/start",
    "POST",
    {},
  );

// --- Leaderboard (institution-scoped) ---
export type LeaderRow = {
  rank: number;
  name: string;
  points: number;
  accuracy: number;
  quizzes: number;
  is_you: boolean;
};
export type Leaderboard = {
  course_id: string | null;
  course_name: string | null;
  courses: { id: string; name: string }[];
  top: LeaderRow[];
  me: LeaderRow | null;
  total: number;
};
export const getLeaderboard = (courseId?: string) =>
  jsonRequest<Leaderboard>(
    `/api/v1/leaderboard${courseId ? `?course_id=${encodeURIComponent(courseId)}` : ""}`,
    "GET",
  );

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
  if (!res.ok)
    throw new Error("We couldn't load the list of courses. Please try again.");
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

// --- Teacher: manage chapters within their subjects ---
export type Chapter = {
  id: string;
  name: string;
  order_index: number;
  quiz_count: number;
  question_count: number;
};
export const listChapters = (subjectId: string) =>
  jsonRequest<Chapter[]>(`/api/v1/subjects/${subjectId}/chapters`, "GET");
export const createChapter = (subjectId: string, name: string) =>
  jsonRequest<Chapter>("/api/v1/chapters", "POST", {
    subject_id: subjectId,
    name,
  });
export const deleteChapter = (id: string) =>
  jsonRequest<{ deleted: string }>(`/api/v1/chapters/${id}`, "DELETE");

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

// Rich institution-admin overview (people, content, accuracy, activity, courses).
export type InstitutionOverview = {
  teachers: number;
  students: number;
  admins: number;
  courses: number;
  subjects: number;
  documents: number;
  quiz_sets: number;
  published_quizzes: number;
  draft_quizzes: number;
  questions: number;
  attempts: number;
  graded_attempts: number;
  accuracy: number;
  pipeline: { pending_review: number; approved: number; rejected: number };
  activity: { date: string; attempts: number }[];
  top_courses: { name: string; students: number }[];
  recent_quiz_sets: { title: string; status: string; created_at: string | null }[];
};
export const getInstitutionOverview = () =>
  jsonRequest<InstitutionOverview>("/api/v1/admin/overview", "GET");

export type InstitutionAnalytics = {
  updated_at: string;
  summary: {
    students: number;
    teachers: number;
    active_week: number;
    inactive_students: number;
    at_risk: number;
    avg_accuracy: number;
    graded_attempts: number;
    published_quizzes: number;
    courses: number;
  };
  trend: {
    attempts_last7: number;
    attempts_prev7: number;
    delta: number;
    has_trend: boolean;
  };
  activity: { date: string; attempts: number }[];
  pipeline: { pending_review: number; approved: number; rejected: number };
  course_perf: {
    name: string;
    students: number;
    published: number;
    accuracy: number;
    attempts: number;
  }[];
  teacher_activity: {
    name: string;
    quiz_sets: number;
    published: number;
    approved: number;
  }[];
  at_risk_students: { name: string; accuracy: number; attempts: number }[];
  findings: QualityFinding[];
};
export const getInstitutionAnalytics = () =>
  jsonRequest<InstitutionAnalytics>("/api/v1/admin/analytics", "GET");
export const getPlatformStats = () =>
  jsonRequest<PlatformStats>("/api/v1/platform/stats", "GET");

// --- Super-admin platform command center ---
export type InstitutionRow = {
  id: string;
  name: string;
  subdomain: string | null;
  created_at: string | null;
  plan_tier: string | null;
  is_active: boolean;
  teachers: number;
  students: number;
  admins: number;
  quiz_sets: number;
  published: number;
  attempts: number;
  accuracy: number;
};
export type ReviewPipelineFull = {
  pending_review: number;
  approved: number;
  rejected: number;
  needs_edit: number;
};
export type PlatformOverview = {
  institutions: number;
  active_institutions: number;
  teachers: number;
  students: number;
  admins: number;
  quiz_sets: number;
  published_quizzes: number;
  questions: number;
  documents: number;
  attempts: number;
  accuracy: number;
  approval_rate: number;
  pipeline: ReviewPipelineFull;
  activity: { date: string; attempts: number }[];
  institutions_table: InstitutionRow[];
};
export const getPlatformOverview = () =>
  jsonRequest<PlatformOverview>("/api/v1/platform/overview", "GET");

export type OnboardInstitutionInput = {
  name: string;
  subdomain: string;
  plan_tier?: string;
  admin_full_name?: string;
  admin_email?: string;
  admin_password?: string;
};
export const onboardInstitution = (input: OnboardInstitutionInput) =>
  jsonRequest<{
    id: string;
    name: string;
    subdomain: string;
    admin: { id: string; email: string } | null;
  }>("/api/v1/platform/tenants", "POST", input);

export type QuestionBankCourse = {
  course: string;
  tenant: string | null;
  questions: number;
  subjects: number;
  chapters: number;
  difficulty: Record<string, number>;
  types: Record<string, number>;
};
export type QuestionBank = {
  total: number;
  courses: QuestionBankCourse[];
  uncategorised: number;
};
export const getQuestionBank = () =>
  jsonRequest<QuestionBank>("/api/v1/platform/question-bank", "GET");

export type AiQualitySignals = {
  measured_from: string | null;
  generated: number;
  reviewed: number;
  approved: number;
  rejected: number;
  kept_as_is: number;
  approved_after_edit: number;
  regenerated: number;
  pending: number;
  approval_rate: number;
  kept_as_is_rate: number;
  by_type: {
    type: string;
    generated: number;
    approved: number;
    kept_as_is: number;
    kept_rate: number;
  }[];
  most_edited_fields: { field: string; count: number }[];
};
export type QualityFinding = {
  severity: "critical" | "warn" | "good" | "info";
  title: string;
  detail: string;
  action: string;
};
export type QualityTrend = {
  keep_rate_last7: number;
  keep_rate_prev7: number;
  keep_rate_delta: number;
  approved_last7: number;
  approved_prev7: number;
  has_trend: boolean;
};
export type AiMonitoring = {
  updated_at: string;
  total_generated: number;
  approval_rate: number;
  published_quizzes: number;
  failures_14d: number;
  pipeline: ReviewPipelineFull;
  by_type: { type: string; total: number; approved: number; approval: number }[];
  by_difficulty: Record<string, number>;
  difficulty_quality: {
    difficulty: string;
    total: number;
    approved: number;
    approval: number;
  }[];
  volume: { date: string; generated: number }[];
  trend: QualityTrend;
  funnel: { stage: string; count: number }[];
  findings: QualityFinding[];
  signals: AiQualitySignals;
};
export const getAiMonitoring = () =>
  jsonRequest<AiMonitoring>("/api/v1/platform/ai-monitoring", "GET");

// --- Super-admin: institution admins ---
export type TenantOption = { id: string; name: string };
export type InstitutionAdmin = {
  id: string;
  full_name: string | null;
  email: string | null;
  institution: string;
};
export type AdminCreateInput = {
  full_name: string;
  email: string;
  password: string;
  tenant_id: string;
};

export const listTenants = () =>
  jsonRequest<TenantOption[]>("/api/v1/tenants", "GET");
export const listAdmins = () =>
  jsonRequest<InstitutionAdmin[]>("/api/v1/admins", "GET");
export const createAdmin = (input: AdminCreateInput) =>
  jsonRequest<{ id: string; email: string }>("/api/v1/admins", "POST", input);
export const deleteAdmin = (id: string) =>
  jsonRequest<{ deleted: string }>(`/api/v1/platform/admins/${id}`, "DELETE");

// --- Teacher class analytics ---
export type QuizAccuracy = {
  set_id: string;
  title: string;
  accuracy: number;
  attempts: number;
};
export type AttentionStudent = {
  name: string;
  initials: string;
  accuracy: number;
  note: string;
};
export type ReviewPipeline = {
  pending_review: number;
  approved: number;
  rejected: number;
};
export type TeacherClassOverview = {
  class_accuracy: number;
  students: number;
  at_risk: number;
  total_attempts: number;
  accuracy_by_quiz: QuizAccuracy[];
  needs_attention: AttentionStudent[];
  top_performers: AttentionStudent[];
  pipeline: ReviewPipeline;
};

export const getTeacherClassOverview = () =>
  jsonRequest<TeacherClassOverview>("/api/v1/teacher/class-overview", "GET");

// --- Teacher class monitor (roster + engagement) ---
export type ClassMonitorStudent = {
  id: string;
  name: string;
  initials: string;
  attempts: number;
  accuracy: number;
  best: number;
  last_active: string | null;
  status: "strong" | "ok" | "at_risk" | "not_started";
};
export type ClassMonitor = {
  summary: {
    students: number;
    active_week: number;
    class_accuracy: number;
    at_risk: number;
    not_started: number;
    total_attempts: number;
  };
  students: ClassMonitorStudent[];
};
export const getClassMonitor = () =>
  jsonRequest<ClassMonitor>("/api/v1/teacher/class-monitor", "GET");

// Full report for one student (teacher, from Class monitor).
export type StudentReport = {
  student: { name: string; initials: string };
  overall: { accuracy: number; quizzes_taken: number; questions_answered: number };
  per_quiz: { title: string; accuracy: number; date: string | null }[];
  weak_areas: { topic: string; accuracy: number; answered: number }[];
};
export const getStudentReport = (studentId: string) =>
  jsonRequest<StudentReport>(`/api/v1/teacher/student-report/${studentId}`, "GET");

// Institution admin: browse every quiz in the institution (any course/subject).
export type AdminQuizSet = {
  id: string;
  title: string;
  status: string;
  subject: string | null;
  course: string | null;
  teacher: string | null;
  questions: number;
  created_at: string | null;
};
export const getAdminQuizSets = () =>
  jsonRequest<AdminQuizSet[]>("/api/v1/admin/quiz-sets", "GET");

// ---------------------------------------------------------------------------
// Blueprint quiz — topic extraction (Slice 6)
// ---------------------------------------------------------------------------

export type ExtractedTopics = {
  document_id: string;
  topics: string[];
};

/** Extract the teachable topics from an uploaded document (Gemini). ~5-15s. */
export const extractTopics = (documentId: string) =>
  jsonRequest<ExtractedTopics>(`/api/v1/documents/${documentId}/topics`, "POST");

export type TopicWeight = "high" | "medium" | "low";
export type BlueprintTopicInput = { name: string; weight: TopicWeight };

export type BlueprintGenerateRequest = {
  document_id: string;
  subject_id: string;
  chapter_name: string;
  selected_topics: BlueprintTopicInput[];
  // How many questions of each type, e.g. { mcq_single: 3, true_false: 2 }.
  type_counts: Record<string, number>;
  cognitive_level: string;
  difficulty: string;
};

export type BlueprintPlan = {
  topics: { name: string; weight: string; num_questions: number }[];
  general: number;
  total: number;
};

export type BlueprintGenerateResponse = {
  quiz_set_id: string;
  variant_id: string;
  provider: string;
  blueprint: BlueprintPlan;
  questions: (GeneratedQuestion & { topic?: string | null })[];
};

/** Blueprint generation: whole-doc coverage weighted to selected topics. ~20-40s. */
export const generateBlueprintQuiz = (req: BlueprintGenerateRequest) =>
  jsonRequest<BlueprintGenerateResponse>(
    "/api/v1/quiz-sets/generate-blueprint",
    "POST",
    req,
  );
