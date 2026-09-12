import { createClient } from "@/lib/supabase";
import { PUBLIC_ENV } from "@/lib/public-env";
import { safeDashboardNext } from "@/lib/safe-next";

let sessionExpiryRedirectStarted = false;
let latestBearerToken: string | null = null;

// Base URL of the FastAPI backend (from .env.local).
const API_BASE = PUBLIC_ENV.apiBaseUrl;
const DEFAULT_TIMEOUT_MS = 20_000;
// 150 MB takes about 10 minutes at 2 Mbps before server-side extraction time.
const DOCUMENT_UPLOAD_TIMEOUT_MS = 15 * 60_000;
// Includes the default 240-second vision call plus upload/database processing.
const QUIZ_EXTRACTION_TIMEOUT_MS = 5 * 60_000;

export type ApiErrorCode =
  | "network_error"
  | "request_timeout"
  | "request_cancelled"
  | "authentication_required"
  | "permission_denied"
  | "not_found"
  | "conflict"
  | "rate_limited"
  | "service_unavailable"
  | "server_error"
  | "request_failed";

export class ApiRequestError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number | null;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: {
      code: ApiErrorCode;
      status?: number | null;
      requestId?: string | null;
      retryable?: boolean;
    },
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.code = options.code;
    this.status = options.status ?? null;
    this.requestId = options.requestId ?? null;
    this.retryable = options.retryable ?? false;
  }
}

function requestReference(requestId: string | null): string {
  return requestId ? ` Error reference: ${requestId}.` : "";
}

async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const upstream = init.signal;
  const abortFromUpstream = () => controller.abort();
  upstream?.addEventListener("abort", abortFromUpstream, { once: true });
  const requestId = crypto.randomUUID();
  const headers = new Headers(init.headers);
  headers.set("X-Request-ID", requestId);
  const method = (init.method ?? "GET").toUpperCase();
  const maxAttempts = method === "GET" ? 2 : 1;
  try {
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        const response = await fetch(input, {
          ...init,
          headers,
          signal: controller.signal,
        });
        const retryableResponse = [502, 503, 504].includes(response.status);
        if (retryableResponse && attempt + 1 < maxAttempts) {
          await new Promise((resolve) => window.setTimeout(resolve, 200));
          continue;
        }
        return response;
      } catch (error) {
        if (
          attempt + 1 < maxAttempts &&
          !controller.signal.aborted &&
          error instanceof TypeError
        ) {
          await new Promise((resolve) => window.setTimeout(resolve, 200));
          continue;
        }
        throw error;
      }
    }
    throw new Error("Request retry state was exhausted.");
  } catch {
    if (controller.signal.aborted) {
      if (timedOut) {
        throw new ApiRequestError(
          `The request timed out. Please check your connection and try again.${requestReference(requestId)}`,
          {
            code: "request_timeout",
            requestId,
            retryable: true,
          },
        );
      }
      throw new ApiRequestError("The request was cancelled.", {
        code: "request_cancelled",
        requestId,
      });
    }
    throw new ApiRequestError(
      `Unable to reach the service. Check your connection and try again.${requestReference(requestId)}`,
      {
        code: "network_error",
        requestId,
        retryable: true,
      },
    );
  } finally {
    window.clearTimeout(timer);
    upstream?.removeEventListener("abort", abortFromUpstream);
  }
}

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
  latestBearerToken = token ?? null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function apiError(res: Response, fallback: string): Promise<never> {
  if (res.status === 401) {
    if (!sessionExpiryRedirectStarted) {
      sessionExpiryRedirectStarted = true;
      try {
        await createClient().auth.signOut({ scope: "local" });
      } finally {
        const next = safeDashboardNext(
          `${window.location.pathname}${window.location.search}`,
        );
        const nextParam = next === "/dashboard" ? "" : `&next=${encodeURIComponent(next)}`;
        window.location.replace(`/login?reason=session-expired${nextParam}`);
      }
    }
    throw new ApiRequestError("Your session expired. Please log in again.", {
      code: "authentication_required",
      status: 401,
      requestId: res.headers.get("X-Request-ID"),
    });
  }
  const body = (await res.json().catch(() => ({}))) as {
    detail?: string;
    request_id?: string;
  };
  const requestId = res.headers.get("X-Request-ID") || body.request_id || null;
  const statusDetails: Record<
    number,
    { code: ApiErrorCode; message: string; retryable: boolean }
  > = {
    403: {
      code: "permission_denied",
      message: body.detail || "You do not have permission to perform this action.",
      retryable: false,
    },
    404: {
      code: "not_found",
      message: body.detail || "The requested item could not be found.",
      retryable: false,
    },
    409: {
      code: "conflict",
      message: body.detail || fallback,
      retryable: false,
    },
    429: {
      code: "rate_limited",
      message: body.detail || "Too many requests. Please wait and try again.",
      retryable: true,
    },
    503: {
      code: "service_unavailable",
      message: body.detail || "The service is temporarily unavailable. Please try again.",
      retryable: true,
    },
  };
  const details = statusDetails[res.status] ?? {
    code: res.status >= 500 ? ("server_error" as const) : ("request_failed" as const),
    message:
      res.status >= 500
        ? "An unexpected server error occurred. Please try again."
        : body.detail || fallback,
    retryable: res.status >= 500,
  };
  throw new ApiRequestError(
    `${details.message}${requestReference(requestId)}`,
    {
      code: details.code,
      status: res.status,
      requestId,
      retryable: details.retryable,
    },
  );
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
  const res = await apiFetch(
    `${API_BASE}/api/v1/documents/upload`,
    {
      method: "POST",
      headers,
      body: form,
    },
    DOCUMENT_UPLOAD_TIMEOUT_MS,
  );

  if (!res.ok) {
    return apiError(res, "We couldn't upload your file. Please try again.");
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Quiz extraction — pull an EXISTING quiz out of an uploaded document
// ---------------------------------------------------------------------------

export type ExtractResult = {
  quiz_set_id: string;
  variant_id: string;
  provider: string;
  extraction_job_id: string;
  extracted: number;
  skipped: number;
  overall_confidence: number | null;
  questions: GeneratedQuestion[];
};

/** Thrown when the same file was already uploaded — caller can retry with force. */
export class DuplicateFileError extends Error {
  readonly code = "duplicate_file";
}

/**
 * Upload an existing quiz document (PDF / DOCX / PNG / JPG) and have the AI
 * provider extract its questions into a draft quiz set for review. This can
 * take several minutes. If the exact file was already uploaded, this throws
 * DuplicateFileError unless `force` is true.
 */
export async function extractQuiz(
  file: File,
  subjectId: string,
  chapterId: string,
  force = false,
): Promise<ExtractResult> {
  const headers = await authHeader();
  const form = new FormData();
  form.append("file", file);
  form.append("subject_id", subjectId);
  form.append("chapter_id", chapterId);
  form.append("force", String(force));
  const res = await apiFetch(
    `${API_BASE}/api/v1/quiz-sets/extract`,
    { method: "POST", headers, body: form },
    QUIZ_EXTRACTION_TIMEOUT_MS,
  );
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    throw new DuplicateFileError(body.detail || "You already uploaded this file.");
  }
  if (!res.ok) {
    return apiError(
      res,
      "We couldn't extract a quiz from this file. Try a clearer scan or a different file.",
    );
  }
  return res.json();
}

/** List the documents uploaded within the caller's tenant. */
export async function listDocuments(): Promise<DocumentOut[]> {
  const headers = await authHeader();
  const res = await apiFetch(`${API_BASE}/api/v1/documents`, { headers });
  if (!res.ok) {
    return apiError(res, "We couldn't load your documents. Please try again.");
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Document log — a teacher's readable history of their uploads
// ---------------------------------------------------------------------------

export type DocumentLogItem = {
  id: string;
  original_filename: string | null;
  file_type: string | null;
  status: string;
  created_at: string;
  subject_name: string | null;
  chapter_name: string | null;
  // What happened to this document:
  // "published" | "draft" | "extracting" | "failed" | "none"
  quiz_status: string;
};

/** The teacher's own uploaded documents, newest first (for the Document Log). */
export async function listDocumentLog(): Promise<DocumentLogItem[]> {
  const headers = await authHeader();
  const res = await apiFetch(`${API_BASE}/api/v1/documents/log`, { headers });
  if (!res.ok) {
    return apiError(res, "We couldn't load your document log. Please try again.");
  }
  return res.json();
}

export type DocumentFileUrl = {
  url: string;
  original_filename: string | null;
  file_type: string | null;
  expires_in: number;
};

/** Get a short-lived link to open/download one of your uploaded documents. */
export async function getDocumentFileUrl(id: string): Promise<DocumentFileUrl> {
  const headers = await authHeader();
  const res = await apiFetch(
    `${API_BASE}/api/v1/documents/${id}/file-url`,
    { headers },
  );
  if (!res.ok) {
    return apiError(res, "We couldn't open this document. Please try again.");
  }
  return res.json();
}

/**
 * Retry extraction on a document that's already uploaded (e.g. a previous
 * attempt where the AI timed out). Reuses the stored file and chapter, so
 * there's no re-upload and no duplicate warning. Returns the new draft's id.
 */
export async function reExtractDocument(
  documentId: string,
): Promise<{ quiz_set_id: string }> {
  const headers = await authHeader();
  const res = await apiFetch(
    `${API_BASE}/api/v1/quiz-sets/${documentId}/re-extract`,
    { method: "POST", headers },
    QUIZ_EXTRACTION_TIMEOUT_MS,
  );
  if (!res.ok) {
    return apiError(res, "We couldn't extract this document. Please try again.");
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
  const res = await apiFetch(`${API_BASE}/api/v1/quiz-sets/generate`, {
    method: "POST",
    headers,
    body: JSON.stringify(req),
  }, 90_000);
  if (!res.ok) {
    return apiError(
      res,
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
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const headers: Record<string, string> = { ...(await authHeader()) };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await apiFetch(
    `${API_BASE}${path}`,
    {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    },
    timeoutMs,
  );
  if (!res.ok) {
    return apiError(res, "Something went wrong. Please try again.");
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
  jsonRequest<ReviewQuestion>(
    `/api/v1/questions/${id}/regenerate`,
    "POST",
    undefined,
    60_000,
  );

export const changePassword = (currentPassword: string, password: string) =>
  jsonRequest<{ changed: boolean }>("/api/v1/auth/change-password", "POST", {
    current_password: currentPassword,
    password,
  });

export const deleteOwnAccount = () =>
  jsonRequest<{ deleted: boolean }>("/api/v1/auth/account", "DELETE", {
    confirmation: "DELETE",
  });

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
  attempt_limit: number;
  attempts_remaining: number;
  best_pct?: number | null;
};

export type StudentQuiz = {
  id: string;
  title: string;
  published_at?: string | null;
  subject_id?: string | null;
  chapter_id?: string | null;
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
  /** A soft pacing guide. The overall attempt deadline remains authoritative. */
  suggested_seconds?: number;
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
  deadline_at?: string | null;
  /** Server-computed at fetch/start time; used to anchor the local display clock. */
  remaining_seconds?: number | null;
  autosave_state?: Record<string, unknown>;
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

// A newly-created attempt already carries its safe, answer-stripped question
// payload. Keep it for exactly one route transition so the taking screen does
// not immediately repeat the same backend reads. Later visits still fetch the
// server state and therefore restore the latest autosave.
const primedAttemptStates = new Map<string, AttemptState>();

function primeAttemptState(state: AttemptState): void {
  primedAttemptStates.set(state.attempt_id, state);
}

export function consumePrimedAttemptState(attemptId: string): AttemptState | null {
  const state = primedAttemptStates.get(attemptId) ?? null;
  primedAttemptStates.delete(attemptId);
  return state;
}

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
  variant_id?: string | null;
  variant_type: string | null;
  subject_id?: string | null;
  chapter_id?: string | null;
  total_score: number | null;
  max_score: number | null;
  submitted_at: string | null;
  source: "quiz" | "practice";
};

/** The student's past graded attempts, newest first. */
export const listStudentAttempts = () =>
  jsonRequest<AttemptHistoryItem[]>("/api/v1/student/attempts", "GET");

export const startAttempt = async (variantId: string) => {
  const state = await jsonRequest<AttemptInProgress>("/api/v1/attempts", "POST", {
    variant_id: variantId,
  });
  primeAttemptState(state);
  return state;
};

export const getAttempt = (attemptId: string) =>
  jsonRequest<AttemptState>(`/api/v1/attempts/${attemptId}`, "GET");

export const submitAttempt = (
  attemptId: string,
  answers: { question_id: string; student_answer: unknown }[],
  finalizeReason: "submit" | "left" = "submit",
) =>
  jsonRequest<AttemptResult>(`/api/v1/attempts/${attemptId}/submit`, "POST", {
    answers,
    finalize_reason: finalizeReason,
  });
export const saveAttemptProgress = (
  attemptId: string,
  answers: Record<string, unknown>,
) =>
  jsonRequest<{ saved: boolean }>(`/api/v1/attempts/${attemptId}/autosave`, "PATCH", {
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
export type PracticeSubject = { id: string; name: string };
export const listPracticeSubjects = () =>
  jsonRequest<PracticeSubject[]>("/api/v1/practice/subjects", "GET");
export const previewPracticeSession = (input: StartPracticeInput) =>
  jsonRequest<{ requested_count: number; question_count: number }>(
    "/api/v1/practice/preview",
    "POST",
    input,
  );
export type StartedPracticeSession = AttemptInProgress & { session_id: string };
export const startPracticeSession = async (input: StartPracticeInput) => {
  const state = await jsonRequest<StartedPracticeSession>(
    "/api/v1/practice/sessions",
    "POST",
    input,
  );
  primeAttemptState(state);
  return state;
};
export const getPracticeSession = (id: string) =>
  jsonRequest<AttemptState>(`/api/v1/practice/sessions/${id}`, "GET");
export const submitPracticeSession = (
  id: string,
  answers: { question_id: string; student_answer: unknown }[],
  finalizeReason: "submit" | "left" = "submit",
) =>
  jsonRequest<AttemptResult>(`/api/v1/practice/sessions/${id}/submit`, "POST", {
    answers,
    finalize_reason: finalizeReason,
  });

type ExitAnswer = { question_id: string; student_answer: unknown };

function exitSubmitUrl(id: string, source: "quiz" | "practice"): string {
  return `${API_BASE}/api/v1/${
    source === "practice" ? `practice/sessions/${id}` : `attempts/${id}`
  }/submit`;
}

/** Grade an intentionally abandoned attempt before client-side navigation. */
export async function finalizeAttemptForExit(
  id: string,
  source: "quiz" | "practice",
  answers: ExitAnswer[],
): Promise<void> {
  const headers = await authHeader();
  const res = await apiFetch(exitSubmitUrl(id, source), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ answers, finalize_reason: "left" }),
    keepalive: true,
  });
  if (!res.ok && res.status !== 400) {
    await apiError(res, "The attempt could not be finalized.");
  }
}

/** Best-effort keepalive used only after the browser confirms a real page exit. */
export function finalizeAttemptOnUnload(
  id: string,
  source: "quiz" | "practice",
  answers: ExitAnswer[],
): void {
  if (!latestBearerToken) return;
  void fetch(exitSubmitUrl(id, source), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${latestBearerToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ answers, finalize_reason: "left" }),
    keepalive: true,
  });
}
export const savePracticeProgress = (
  id: string,
  answers: Record<string, unknown>,
) =>
  jsonRequest<{ saved: boolean }>(`/api/v1/practice/sessions/${id}/autosave`, "PATCH", {
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
  rank: number;
  name: string;
  pct: number;
  elapsed_seconds: number | null;
  is_creator: boolean;
  is_you: boolean;
};
export type ChallengeInfo = {
  token: string;
  creator_name: string;
  subject_name: string | null;
  questions: number;
  type_counts: Record<string, number>;
  duration_minutes: number | null;
  expires_at: string | null;
  is_active: boolean;
  accepting_closed: boolean;
  is_creator: boolean;
  my_status: "not_taken" | "in_progress" | "done";
  my_session_id: string | null;
  my_pct: number | null;
  leaderboard: ChallengeLeaderRow[];
};
export type MyChallenge = {
  token: string;
  subject_name: string | null;
  questions: number;
  duration_minutes: number | null;
  created_at: string | null;
  expires_at: string | null;
  is_active: boolean;
  is_expired: boolean;
  players: number;
  my_status: "not_taken" | "in_progress" | "done";
  my_session_id: string | null;
};
export const listMyChallenges = () =>
  jsonRequest<MyChallenge[]>("/api/v1/challenges/mine", "GET");
export type CreatedChallenge = {
  token: string;
  questions: number;
  duration_minutes: number;
  type_counts: Record<string, number>;
};
export const createChallenge = (input: {
  subject_id?: string | null;
  type_counts: Record<string, number>;
}) =>
  jsonRequest<CreatedChallenge>(
    "/api/v1/challenges",
    "POST",
    input,
  );
export const getChallenge = (token: string) =>
  jsonRequest<ChallengeInfo>(`/api/v1/challenges/${token}`, "GET");
export const acceptChallenge = async (token: string) => {
  const state = await jsonRequest<StartedPracticeSession>(
    `/api/v1/challenges/${token}/accept`,
    "POST",
    {},
  );
  primeAttemptState(state);
  return state;
};
export const closeChallenge = (token: string) =>
  jsonRequest<{ closed: string }>(`/api/v1/challenges/${token}`, "DELETE");

// --- Daily challenge + streak ---
export type DailyInfo = {
  done_today: boolean;
  attempted_today: boolean;
  streak: number;
  longest: number;
  today_session_id: string | null;
  last7: { date: string; done: boolean }[];
};
export const getDaily = () => jsonRequest<DailyInfo>("/api/v1/daily", "GET");
export const startDaily = async () => {
  const state = await jsonRequest<StartedPracticeSession>(
    "/api/v1/daily/start",
    "POST",
    {},
  );
  primeAttemptState(state);
  return state;
};

// --- Exam Simulator (timed, negative marking, per-institution pattern) ---
export type ExamConfig = {
  questions: number;
  duration_minutes: number;
  negative_marking: number;
  active_session_id: string | null;
};
export const getExamConfig = () =>
  jsonRequest<ExamConfig>("/api/v1/exam/config", "GET");
export const startExam = async () => {
  const state = await jsonRequest<StartedPracticeSession>(
    "/api/v1/exam/start",
    "POST",
    {},
  );
  primeAttemptState(state);
  return state;
};

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
export type Course = {
  id: string;
  name: string;
  subjects: Subject[];
  student_count?: number;
};

export const listCourses = () => jsonRequest<Course[]>("/api/v1/courses", "GET");

/** Public (no-auth) course list for the signup dropdown. */
export async function listPublicCourses(
  tenantId: string,
): Promise<{ id: string; name: string }[]> {
  const res = await apiFetch(
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

export const getTeacherSubjects = (teacherId: string) =>
  jsonRequest<{ subject_ids: string[] }>(
    `/api/v1/teachers/${teacherId}/subjects`,
    "GET",
  );

export const setTeacherSubjects = (teacherId: string, subjectIds: string[]) =>
  jsonRequest<{ subject_ids: string[] }>(
    `/api/v1/teachers/${teacherId}/subjects`,
    "PUT",
    { subject_ids: subjectIds },
  );

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

// Per-subject teaching metrics for the Subjects dashboard.
export type SubjectMetrics = {
  id: string;
  name: string;
  course_name: string;
  chapters: number;
  quizzes_total: number;
  quizzes_published: number;
  quizzes_draft: number;
  questions: number;
  pending_review: number;
  attempts: number;
  students: number;
  avg_score_pct: number | null;
  score_earned: number;
  score_possible: number;
};
export const listSubjectMetrics = () =>
  jsonRequest<SubjectMetrics[]>("/api/v1/teacher/subject-metrics", "GET");

// ---------------------------------------------------------------------------
// Admin: users + analytics
// ---------------------------------------------------------------------------

export type AdminUser = {
  id: string;
  full_name: string | null;
  email: string | null;
  courses: string[];
  subject_count: number;
};

export type TeacherCreateInput = {
  full_name: string;
  email: string;
  password: string;
  course_id: string;
  subject_ids: string[];
};

export type TeacherUpdateInput = {
  full_name: string;
  email: string;
  subject_ids: string[];
};

export type TeacherCourse = {
  id: string;
  name: string;
  subjects: { id: string; name: string }[];
  student_count: number;
};

export type CourseStudent = {
  id: string;
  full_name: string | null;
  email: string | null;
};

export type CourseRoster = {
  course: { id: string; name: string };
  count: number;
  students: CourseStudent[];
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
export const createTeacher = (input: TeacherCreateInput) =>
  jsonRequest<{ id: string }>("/api/v1/users", "POST", input);
export const updateTeacher = (id: string, input: TeacherUpdateInput) =>
  jsonRequest<{ changed: boolean }>(
    `/api/v1/users/${id}`,
    "PUT",
    input,
  );
export const resetTeacherTemporaryPassword = (id: string, password: string) =>
  jsonRequest<{ changed: boolean }>(
    `/api/v1/users/${id}/temporary-password`,
    "POST",
    { password },
  );
export const deleteUser = (id: string) =>
  jsonRequest<{ deleted: boolean }>(`/api/v1/users/${id}`, "DELETE");
export const listTeacherCourses = (teacherId: string) =>
  jsonRequest<TeacherCourse[]>(`/api/v1/teachers/${teacherId}/courses`, "GET");
export const listCourseStudents = (courseId: string) =>
  jsonRequest<CourseRoster>(`/api/v1/courses/${courseId}/students`, "GET");
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
    admins: number;
    active_week: number;
    inactive_students: number;
    at_risk: number;
    avg_accuracy: number;
    graded_attempts: number;
    published_quizzes: number;
    quiz_sets: number;
    courses: number;
    subjects: number;
    documents: number;
    draft_quizzes: number;
    questions: number;
  };
  trend: {
    attempts_last7: number;
    attempts_prev7: number;
    delta: number;
    percentage_change: number;
    has_trend: boolean;
  };
  activity: { date: string; attempts: number }[];
  pipeline: { pending_review: number; approved: number; rejected: number };
  course_perf: {
    course_id: string;
    name: string;
    students: number;
    published: number;
    pending_review: number;
    accuracy: number;
    attempts: number;
  }[];
  teacher_activity: {
    teacher_id: string;
    name: string;
    quiz_sets: number;
    published: number;
    approved: number;
    attempts: number;
    accuracy: number;
    last_quiz_created: string | null;
    is_active: boolean;
  }[];
  at_risk_students: {
    student_id: string;
    name: string;
    accuracy: number;
    attempts: number;
    worst_quiz: {
      quiz_set_id: string;
      title: string;
      accuracy: number;
      attempts: number;
      last_attempted_at: string | null;
    } | null;
    quizzes: {
      quiz_set_id: string;
      title: string;
      accuracy: number;
      attempts: number;
      last_attempted_at: string | null;
    }[];
  }[];
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
  jsonRequest<{ created: boolean }>("/api/v1/platform/tenants", "POST", input);

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
  action_type?: "pending_review" | "at_risk" | "course" | "teacher" | null;
  action_id?: string | null;
  action_label?: string | null;
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
  jsonRequest<{ created: boolean }>("/api/v1/admins", "POST", input);
export const deleteAdmin = (id: string) =>
  jsonRequest<{ deleted: boolean }>(`/api/v1/platform/admins/${id}`, "DELETE");

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
export type ActivityPoint = { date: string; count: number };
export type ScoreBand = { label: string; count: number };
export type TeacherClassOverview = {
  class_accuracy: number;
  students: number;
  at_risk: number;
  total_attempts: number;
  accuracy_by_quiz: QuizAccuracy[];
  needs_attention: AttentionStudent[];
  top_performers: AttentionStudent[];
  pipeline: ReviewPipeline;
  activity_trend: ActivityPoint[];
  score_distribution: ScoreBand[];
  content: {
    documents: number;
    quiz_sets: number;
    published: number;
    drafts: number;
  };
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
  subject_id: string | null;
  course: string | null;
  course_id: string | null;
  teacher: string | null;
  teacher_id: string | null;
  questions: number;
  attempts_count: number;
  avg_accuracy: number;
  created_at: string | null;
  published_at: string | null;
  last_attempted_at: string | null;
  review_status: {
    pending: number;
    approved: number;
    rejected: number;
    needs_edit: number;
  };
};
export const getAdminQuizSets = (teacherId?: string) =>
  jsonRequest<AdminQuizSet[]>(
    `/api/v1/admin/quiz-sets${teacherId ? `?teacher_id=${encodeURIComponent(teacherId)}` : ""}`,
    "GET",
  );

export type TeacherAnalyticsSummary = {
  total_teachers: number;
  active_teachers: number;
  avg_accuracy: number;
  total_quiz_sets: number;
  total_published: number;
  total_attempts: number;
};

export type TeacherAnalyticsDetail = {
  teacher_id: string;
  teacher_name: string;
  quiz_sets_created: number;
  quiz_sets_published: number;
  total_attempts: number;
  avg_accuracy: number;
  last_quiz_created: string | null;
  is_active: boolean;
  course_names: string[];
};

export type TeacherAnalytics = {
  teachers: TeacherAnalyticsDetail[];
  summary: TeacherAnalyticsSummary;
};

export const getTeacherAnalytics = () =>
  jsonRequest<TeacherAnalytics>("/api/v1/admin/teachers/analytics", "GET");

export type AdminQuizSetDetail = {
  quiz: AdminQuizSet;
  question_breakdown: {
    by_type: Record<string, number>;
    by_difficulty: Record<string, number>;
  };
  student_performance: {
    attempt_id: string;
    student_id: string;
    student_name: string;
    score: number;
    max_score: number;
    accuracy: number;
    submitted_at: string | null;
  }[];
  weak_questions: {
    question_id: string;
    question_text: string;
    answered: number;
    accuracy: number;
  }[];
};
export const getAdminQuizSetDetail = (id: string) =>
  jsonRequest<AdminQuizSetDetail>(`/api/v1/admin/quiz-sets/${id}`, "GET");

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

/** Blueprint generation (small documents): whole-doc coverage weighted to
 * selected topics, in one AI call. ~20-40s. */
export const generateBlueprintQuiz = (req: BlueprintGenerateRequest) =>
  jsonRequest<BlueprintGenerateResponse>(
    "/api/v1/quiz-sets/generate-blueprint",
    "POST",
    req,
    90_000,
  );

// --- Large-document analysis (chunked Map-Reduce) -------------------------
// Route a document by size: a small document returns its topics immediately;
// a large one starts a resumable background analysis job to poll.
export type AnalyzeResponse =
  | { mode: "direct"; document_id: string; topics: string[] }
  | { mode: "job"; document_id: string; job_id: string; status: string };

/** Route a document by size (extract text server-side; ~5-20s for large PDFs). */
export const analyzeDocument = (documentId: string) =>
  jsonRequest<AnalyzeResponse>(
    "/api/v1/quiz-sets/analyze",
    "POST",
    { document_id: documentId },
    120_000,
  );

export type GenerationJobStatus = {
  job_id: string;
  status: "queued" | "running" | "partial" | "completed" | "failed";
  phase: string;
  total_chunks: number;
  done_chunks: number;
  error_message: string | null;
  // The Master Blueprint's consolidated topics (present once the job is ready).
  topics: {
    name: string;
    subtopics: string[];
    page_ranges: { start: number; end: number }[];
  }[];
  quiz_set_id: string | null;
};

export const getGenerationJob = (jobId: string) =>
  jsonRequest<GenerationJobStatus>(
    `/api/v1/quiz-sets/generation-jobs/${jobId}`,
    "GET",
  );

export const retryGenerationJob = (jobId: string) =>
  jsonRequest<{ status: string; job_id: string }>(
    `/api/v1/quiz-sets/generation-jobs/${jobId}/retry`,
    "POST",
  );

/** Generate the quiz from a ready analysis job's Master Blueprint (single AI
 * call), then hand off to review — same result shape as small-doc generation. */
export const generateFromJob = (
  jobId: string,
  req: Omit<BlueprintGenerateRequest, "document_id">,
) =>
  jsonRequest<BlueprintGenerateResponse & { job_id: string }>(
    `/api/v1/quiz-sets/generation-jobs/${jobId}/generate`,
    "POST",
    req,
    90_000,
  );
