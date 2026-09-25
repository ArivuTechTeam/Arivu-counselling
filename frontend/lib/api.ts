import { createClient } from "@/lib/supabase";
import { PUBLIC_ENV } from "@/lib/public-env";
import { safeDashboardNext } from "@/lib/safe-next";

let sessionExpiryRedirectStarted = false;

// Base URL of the FastAPI backend (from .env.local).
const API_BASE = PUBLIC_ENV.apiBaseUrl;
const DEFAULT_TIMEOUT_MS = 20_000;
// Legacy synchronous generation includes writing, verification and bounded
// repairs/provider fallback. Prefer durable faculty jobs when enabled.
const QUIZ_GENERATION_TIMEOUT_MS = 15 * 60_000;
export const DOCUMENT_UPLOAD_MAX_MB = 30;
export const DOCUMENT_UPLOAD_MAX_BYTES = DOCUMENT_UPLOAD_MAX_MB * 1024 * 1024;
// A 30 MiB upload can still take several minutes on a slow connection before
// server-side extraction begins.
const DOCUMENT_UPLOAD_TIMEOUT_MS = 15 * 60_000;
// Includes the default 240-second vision call plus upload/database processing.
const QUIZ_EXTRACTION_TIMEOUT_MS = 5 * 60_000;

/**
 * Start a sleeping API service while authentication/profile work is already in
 * flight. This is deliberately best-effort: sign-in must never fail because a
 * liveness request failed, and the real authenticated request still reports
 * any backend error normally.
 */
export function warmBackend(): void {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 8_000);
  void fetch(`${API_BASE}/health`, {
    method: "GET",
    cache: "no-store",
    signal: controller.signal,
  })
    .catch(() => undefined)
    .finally(() => window.clearTimeout(timer));
}

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
  readonly retryAfterSeconds: number | null;
  readonly reason: string | null;

  constructor(
    message: string,
    options: {
      code: ApiErrorCode;
      status?: number | null;
      requestId?: string | null;
      retryable?: boolean;
      retryAfterSeconds?: number | null;
      reason?: string | null;
    },
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.code = options.code;
    this.status = options.status ?? null;
    this.requestId = options.requestId ?? null;
    this.retryable = options.retryable ?? false;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
    this.reason = options.reason ?? null;
  }
}

type ValidationErrorDetail = {
  location?: Array<string | number>;
  message?: string;
};

function validationErrorMessage(errors: ValidationErrorDetail[] | undefined): string | null {
  if (!Array.isArray(errors) || errors.length === 0) return null;
  const messages = errors.slice(0, 3).map((error) => {
    const field = (error.location ?? [])
      .filter((part) => !["body", "query", "path"].includes(String(part)))
      .map((part) => String(part).replaceAll("_", " "))
      .join(" → ");
    const message = error.message || "Invalid value.";
    return field ? `${field}: ${message}` : message;
  });
  return messages.join(" ");
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
          timeoutMs >= QUIZ_EXTRACTION_TIMEOUT_MS
            ? "Processing is taking longer than this page can wait. Check Recent tasks and the Review queue before starting again; the server may still finish this request."
            : "The service did not respond in time. Please try again shortly.",
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
      "Unable to reach the service. Check your connection and try again.",
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
    errors?: ValidationErrorDetail[];
    request_id?: string;
  };
  const requestId = res.headers.get("X-Request-ID") || body.request_id || null;
  const reason = res.headers.get("X-Error-Code");
  const retryAfterHeader = res.headers.get("Retry-After");
  const parsedRetryAfter = retryAfterHeader
    ? Number.parseInt(retryAfterHeader, 10)
    : Number.NaN;
  const retryAfterSeconds = Number.isFinite(parsedRetryAfter)
    ? Math.max(0, parsedRetryAfter)
    : null;
  const statusDetails: Record<
    number,
    { code: ApiErrorCode; message: string; retryable: boolean }
  > = {
    422: {
      code: "request_failed",
      message:
        validationErrorMessage(body.errors) ||
        body.detail ||
        "Please check the submitted fields and try again.",
      retryable: false,
    },
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
    502: {
      code: "service_unavailable",
      message: "The service is temporarily unavailable. Please try again in a moment.",
      retryable: true,
    },
    504: {
      code: "request_timeout",
      message: "The service took too long to respond. Please try again in a moment.",
      retryable: true,
    },
  };
  const details = statusDetails[res.status] ?? {
    code: res.status >= 500 ? ("server_error" as const) : ("request_failed" as const),
    message:
      res.status >= 500
        ? "We couldn't complete this request right now. Please try again. If it keeps happening, contact support."
        : body.detail || fallback,
    retryable: res.status >= 500,
  };
  throw new ApiRequestError(
    details.message,
    {
      code: details.code,
      status: res.status,
      requestId,
      retryable: details.retryable,
      retryAfterSeconds,
      reason,
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
  if (file.size === 0) {
    throw new Error("The selected file is empty.");
  }
  if (file.size > DOCUMENT_UPLOAD_MAX_BYTES) {
    throw new Error(
      `Choose a file no larger than ${DOCUMENT_UPLOAD_MAX_MB} MB.`,
    );
  }
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

export type ImportSummary = {
  source_inventory?: {
    detected: number; matched: number; coverage_verified: boolean; scope: string;
    missing: { source_id: string; source_number: string; question_preview: string }[];
    duplicate_matches: string[]; warnings: string[];
    items: { source_id: string; source_number: string; candidate_index: number; answer_origin: string; state: string }[];
  } | null;
  source_manifest?: { route: string; sparse_pages: number[]; pages: { page: number; text_characters: number }[] } | null;
  candidates: number;
  imported: number;
  skipped: number;
  coverage_verified: boolean;
  issues: { candidate_index: number; question_preview: string; reason: string }[];
};

export type ExtractResult = {
  quiz_set_id: string;
  variant_id: string;
  provider: string;
  extraction_job_id: string;
  extracted: number;
  skipped: number;
  import_summary?: ImportSummary;
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
  analyzePapers = false,
): Promise<ExtractResult | QueuedFacultyResponse> {
  const headers = await authHeader();
  const background = (await listFacultyJobs()).enabled;
  const form = new FormData();
  form.append("file", file);
  form.append("subject_id", subjectId);
  form.append("chapter_id", chapterId);
  form.append("force", String(force));
  form.append("analyze_papers", String(analyzePapers));
  if (background) {
    form.append("background", "true");
    form.append("request_key", crypto.randomUUID());
  }
  const send = () => apiFetch(`${API_BASE}/api/v1/quiz-sets/extract`,
    { method: "POST", headers, body: form }, QUIZ_EXTRACTION_TIMEOUT_MS);
  let res: Response;
  try { res = await send(); } catch (error) {
    if (!background || !(error instanceof ApiRequestError) || !["network_error", "request_timeout"].includes(error.code)) throw error;
    res = await send(); // Preserve the same form/request key after a lost acknowledgement.
  }
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

/** Soft-archive an upload; its stored file and dependent quiz history remain. */
export const archiveDocument = (id: string) =>
  jsonRequest<{ id: string; status: string }>(
    `/api/v1/documents/${id}/archive`,
    "POST",
  );

/**
 * Retry extraction on a document that's already uploaded (e.g. a previous
 * attempt where the AI timed out). Reuses the stored file and chapter, so
 * there's no re-upload and no duplicate warning. Returns the new draft's id.
 */
export async function reExtractDocument(
  documentId: string,
): Promise<{ quiz_set_id: string } | QueuedFacultyResponse> {
  if ((await listFacultyJobs()).enabled) {
    const body = { request_key: crypto.randomUUID() };
    const send = () => jsonRequest<QueuedFacultyResponse>(`/api/v1/quiz-sets/${documentId}/re-extract`, "POST", body);
    try { return await send(); } catch (error) {
      if (!(error instanceof ApiRequestError) || !["network_error", "request_timeout"].includes(error.code)) throw error;
      return send();
    }
  }
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
  source_excerpt?: string | null;
  source_page_start?: number | null;
  source_page_end?: number | null;
  grounding_confidence?: number | null;
  verification_status?: string | null;
  verification_warnings?: string[];
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

/** A figure extracted from the source document (Phase 2), with a signed URL. */
export type DocumentFigure = {
  id: string;
  page?: number | null;
  label?: string | null;
  caption?: string | null;
  url?: string | null;
  width?: number | null;
  height?: number | null;
};

export type ReviewQuestion = {
  content_version?: number | null;
  release_locked?: boolean;
  id: string;
  type: string;
  question_text: string;
  options?: { id: string; text: string }[] | null;
  correct_answer: unknown;
  explanation?: string | null;
  difficulty?: string;
  marks?: number;
  review_status: string;
  source?: string | null;
  confidence_score?: number | null;
  source_excerpt?: string | null;
  source_page_start?: number | null;
  source_page_end?: number | null;
  grounding_confidence?: number | null;
  verification_status?: string | null;
  verification_warnings?: string[];
  figure_id?: string | null;
  figure?: DocumentFigure | null;
  paper_type?: "pyq" | "mtp" | "rtp" | null;
  paper_year?: string | null;
  paper_exam?: string | null;
  model_answer?: string | null;
};

export type QuizSetDetail = QuizSetSummary & {
  publication_token?: string;
  release_locked?: boolean;
  reuse_enabled?: boolean;
  document_id?: string | null;
  scoring_policy_id?: string | null;
  import_summaries?: (ImportSummary & { extraction_job_id: string })[];
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
    return apiError(res, "We couldn't complete this request. Please try again.");
  }
  return res.json();
}

export type DashboardProfile = {
  role: string;
  must_change_password: boolean;
  institution: {
    name: string;
    subdomain: string;
    logo_url: string | null;
    primary_color: string;
  } | null;
  features: InstitutionFeatureFlags;
};

export type InstitutionFeatureFlags = {
  faculty_jobs: boolean;
  quiz_reuse: boolean;
  batches: boolean;
  scoring_policies: boolean;
  commerce_pack: boolean;
  figure_attach: boolean;
  // Separate paper-bank (PYQ/MTP/RTP) rollout toggle; always present on the
  // /me/profile response, optional here so the 6-key fallbacks stay valid.
  paper_bank?: boolean;
  // Separate P6.4 rollout toggle (not part of the commerce registry); always
  // present on the /me/profile response, optional here so the 6-key fallbacks
  // elsewhere remain valid.
  extended_question_types?: boolean;
};

export const getDashboardProfile = () =>
  jsonRequest<DashboardProfile>("/api/v1/me/profile", "GET");

// --- Mock Test & PYQ student surface (KB-D): PYQ / MTP / RTP ---
export type PaperType = "pyq" | "mtp" | "rtp";
export type PaperSubject = { subject_id: string; subject_name: string; count: number };
export type PaperFilters = {
  total: number;
  chapters: { chapter_id: string; chapter_name: string; count: number }[];
  question_types: { type: string; count: number }[];
};
export type PaperTakeQuestion = {
  id: string;
  type: string;
  question_text: string;
  options?: { id: string; text: string }[] | null;
  marks?: number;
  exam?: string | null;
  year?: string | null;
};
export type PaperResult = {
  question_id: string;
  type: string;
  question_text: string;
  options?: { id: string; text: string }[] | null;
  student_answer: unknown;
  correct_answer: unknown;
  explanation?: string | null;
  is_correct: boolean;
  marks_awarded: number;
};
export type PaperScorecard = {
  attempt_id: string;
  status: "graded";
  score: number;
  total: number;
  correct: number;
  count: number;
  results: PaperResult[];
};
export type PaperStart = {
  paper_type: PaperType;
  subject_id: string;
  chapter_id?: string | null;
  question_type?: string | null;
  count: number;
};
export type PaperTaking = {
  attempt_id: string;
  status: "in_progress";
  paper_type: PaperType;
  requested: number;
  available: number;
  questions: PaperTakeQuestion[];
};

export type PaperBankSummary = {
  totals: { pyq: number; mtp: number; rtp: number; total: number };
  subjects: { subject_id: string; subject_name: string; pyq: number; mtp: number; rtp: number; total: number }[];
};
export const getPaperBank = () =>
  jsonRequest<PaperBankSummary>("/api/v1/papers/bank", "GET");

export const listPaperSubjects = (paperType: PaperType) =>
  jsonRequest<PaperSubject[]>(`/api/v1/papers/subjects?paper_type=${paperType}`, "GET");

export const getPaperFilters = (paperType: PaperType, subjectId: string) =>
  jsonRequest<PaperFilters>(
    `/api/v1/papers/filters?paper_type=${paperType}&subject_id=${encodeURIComponent(subjectId)}`,
    "GET",
  );

export const startPaperAttempt = (body: PaperStart) =>
  jsonRequest<PaperTaking>(
    "/api/v1/papers/start", "POST", body,
  );

export const getPaperAttempt = (id: string) =>
  jsonRequest<PaperTaking | PaperScorecard>(
    `/api/v1/papers/attempts/${encodeURIComponent(id)}`, "GET",
  );

export const submitPaperAttempt = (
  attemptId: string,
  answers: { question_id: string; student_answer: unknown }[],
) => jsonRequest<PaperScorecard>("/api/v1/papers/submit", "POST", { attempt_id: attemptId, answers });

async function listBoundedPages<T>(
  path: string,
  extraParams?: URLSearchParams,
): Promise<T[]> {
  const pageSize = 100;
  const items: T[] = [];
  for (let page = 1; ; page += 1) {
    const params = new URLSearchParams(extraParams);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    const batch = await jsonRequest<T[]>(`${path}?${params.toString()}`, "GET");
    items.push(...batch);
    if (batch.length < pageSize) return items;
  }
}

export const listQuizSets = (archived = false) =>
  listBoundedPages<QuizSetSummary>("/api/v1/quiz-sets", new URLSearchParams({ archived: String(archived) }));

export const restoreQuizSet = (id: string) =>
  jsonRequest<QuizSetSummary>(`/api/v1/quiz-sets/${id}/restore`, "POST");

export const getQuizSet = (id: string) =>
  jsonRequest<QuizSetDetail>(`/api/v1/quiz-sets/${id}`, "GET");

export const editQuestion = (id: string, patch: QuestionPatch, expectedVersion?: number | null) =>
  jsonRequest<ReviewQuestion>(`/api/v1/questions/${id}`, "PATCH", { ...patch, expected_version: expectedVersion });

export const approveQuestion = (id: string, resolutionNote?: string) =>
  jsonRequest<ReviewQuestion>(`/api/v1/questions/${id}/approve`, "POST",
    resolutionNote ? { resolution_note: resolutionNote } : undefined);

export const rejectQuestion = (id: string) =>
  jsonRequest<ReviewQuestion>(`/api/v1/questions/${id}/reject`, "POST");

/** Attach (or, with figureId=null, remove) a source-document figure on a question. */
export const setQuestionFigure = (id: string, figureId: string | null) =>
  jsonRequest<ReviewQuestion>(`/api/v1/questions/${id}/figure`, "PUT", {
    figure_id: figureId,
  });

/** The catalog of figures extracted from a source document (Phase 2). */
export const listDocumentFigures = (documentId: string) =>
  jsonRequest<DocumentFigure[]>(`/api/v1/documents/${documentId}/figures`, "GET");

/** Fetch a question figure's PNG (auth'd with the caller's bearer token) as an
 *  object URL. Students use this so figures render from a same-origin, per-user
 *  authorized stream with no signed-URL expiry mid-attempt. Remember to
 *  URL.revokeObjectURL() the result when the image unmounts. */
export async function fetchFigureObjectUrl(figureId: string): Promise<string> {
  const res = await apiFetch(`${API_BASE}/api/v1/figures/${figureId}`, {
    headers: { ...(await authHeader()) },
  });
  if (!res.ok) throw new Error("Figure image unavailable.");
  return URL.createObjectURL(await res.blob());
}

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

export type AcademicAccess = {
  course: string;
  level: string | null;
  subjects: string[];
};

export type AccountSettings = {
  full_name: string | null;
  email: string | null;
  role: string;
  academic_access: AcademicAccess[];
};

export const getAccountSettings = () =>
  jsonRequest<AccountSettings>("/api/v1/auth/settings", "GET");

export type StudentContactKind = "feedback" | "support";
export type StudentContactCategory = "general" | "feature_idea" | "course_access" | "quiz_issue" | "app_bug";
export type StudentContact = {
  reference: string;
  kind: StudentContactKind;
  category: StudentContactCategory;
  routed_to: "platform" | "institution";
  message: string;
  rating: number | null;
  status: "open" | "answered" | "closed";
  reply: string | null;
  created_at: string;
  updated_at: string;
  institution_name: string | null;
};

export type StudentContactReceipt = Pick<StudentContact, "reference" | "routed_to" | "status">;

export const submitStudentContact = (input: {
  kind: StudentContactKind;
  category: StudentContactCategory;
  message: string;
  rating?: number | null;
}) => jsonRequest<StudentContactReceipt>("/api/v1/contact", "POST", input);

export const getMyStudentContacts = () =>
  jsonRequest<StudentContact[]>("/api/v1/contact/mine", "GET");

export const getSupportInbox = () =>
  jsonRequest<StudentContact[]>("/api/v1/contact/inbox", "GET");

export const replyToStudentContact = (
  reference: string,
  reply: string,
  status: "answered" | "closed" = "answered",
) => jsonRequest<StudentContact>(
  `/api/v1/contact/inbox/${encodeURIComponent(reference)}/reply`,
  "POST",
  { reply, status },
);

export const deleteOwnAccount = () =>
  jsonRequest<{ deleted: boolean }>("/api/v1/auth/account", "DELETE", {
    confirmation: "DELETE",
  });

export const publishQuizSet = (id: string, publicationToken?: string, batchIds?: string[]) =>
  jsonRequest<QuizSetSummary>(`/api/v1/quiz-sets/${id}/${batchIds ? "publish-to-batches" : "publish"}`, "POST",
    publicationToken ? { publication_token: publicationToken, ...(batchIds ? { batch_ids: batchIds } : {}) } : undefined);

export const duplicateQuizSet = (id: string, title: string, requestKey: string) =>
  jsonRequest<{ quiz_set_id: string; replayed: boolean }>(`/api/v1/quiz-sets/${id}/duplicate`, "POST",
    { title, request_key: requestKey }, 90_000);

/** Unpublish and soft-archive a quiz without deleting attempts or analytics. */
export const archiveQuizSet = (id: string) =>
  jsonRequest<QuizSetSummary>(`/api/v1/quiz-sets/${id}/archive`, "POST");

/** Bulk-approve only still-pending questions whose verification is verified. */
export const approveAllQuestions = (id: string) =>
  jsonRequest<{ approved: number; skipped?: number }>(`/api/v1/quiz-sets/${id}/approve-all`, "POST", undefined, 90_000);

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
  /** Source-document figure attached to this question (Phase 2), if any. */
  figure_id?: string | null;
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
export type PracticeChapter = { id: string; name: string };
export const listPracticeSubjects = () =>
  jsonRequest<PracticeSubject[]>("/api/v1/practice/subjects", "GET");
export const listPracticeChapters = (subjectId: string) =>
  jsonRequest<PracticeChapter[]>(
    `/api/v1/practice/subjects/${encodeURIComponent(subjectId)}/chapters`,
    "GET",
  );
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
  });
  if (!res.ok) {
    await apiError(res, "The attempt could not be finalized.");
  }
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
  join_code: string | null;
  institution_slug: string | null;
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
  join_code: string | null;
  institution_slug: string | null;
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
  join_code: string;
  institution_slug: string | null;
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
export const joinChallenge = (code: string) =>
  jsonRequest<{ token: string }>("/api/v1/challenges/join", "POST", { code });
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
  penalty_is_fraction: boolean;
  partial_credit: boolean;
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

export type Subject = {
  id: string;
  name: string;
  course_level_id?: string;
  catalog_subject_id?: string;
  catalog_level_id?: string;
  level_name?: string;
};
export type Course = {
  id: string;
  name: string;
  subjects: Subject[];
  levels?: { id: string; name: string; catalog_level_id?: string | null }[];
  student_count?: number;
};

export type PublicCourseLevel = { id: string; name: string };
export type PublicCourse = {
  id: string;
  name: string;
  levels: PublicCourseLevel[];
};

export type CatalogSubject = {
  id: string;
  name: string;
  offered: boolean;
};
export type CatalogLevel = {
  id: string;
  name: string;
  subjects: CatalogSubject[];
};
export type CatalogCourse = {
  id: string;
  code: string;
  name: string;
  levels: CatalogLevel[];
};

export const getCourseCatalog = (tenantId?: string) =>
  jsonRequest<CatalogCourse[]>(
    `/api/v1/catalog${tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ""}`,
    "GET",
  );

export const provisionCatalogSubjects = (
  catalogSubjectIds: string[],
  tenantId?: string,
) =>
  jsonRequest<{ provisioned: number; collisions: string[] }>(
    `/api/v1/catalog/provision${tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ""}`,
    "POST",
    { catalog_subject_ids: catalogSubjectIds },
  );

export const listCourses = () => jsonRequest<Course[]>("/api/v1/courses", "GET");

/** Public (no-auth) course list for the signup dropdown. */
export async function listPublicCourses(
  tenantId: string,
): Promise<PublicCourse[]> {
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

export const createCourseLevel = (courseId: string, name: string) =>
  jsonRequest<{ id: string; name: string }>("/api/v1/course-levels", "POST", {
    course_id: courseId,
    name,
  });

export const createSubject = (courseId: string, courseLevelId: string, name: string) =>
  jsonRequest<Subject>("/api/v1/subjects", "POST", {
    course_id: courseId,
    course_level_id: courseLevelId,
    name,
  });

// --- Batches, rostering & assignments (Phase 6.1) ---
export type Batch = {
  id: string;
  course_id: string;
  course_level_id: string;
  name: string;
  exam_session?: string | null;
  status: string;
  created_at?: string | null;
};
export type BatchMember = {
  id: string;
  profile_id: string;
  membership_role: string;
  active: boolean;
  full_name?: string | null;
  created_at?: string | null;
};
export type QuizAssignment = {
  id: string;
  batch_id: string;
  available_from?: string | null;
  available_to?: string | null;
  status: string;
  created_at?: string | null;
};

/** Public (no-auth) batch list for the signup dropdown, filtered by course. */
export async function listPublicBatches(
  tenantId: string,
  courseId: string,
  courseLevelId: string,
): Promise<{ id: string; name: string }[]> {
  const res = await apiFetch(
    `${API_BASE}/api/v1/public/batches?tenant_id=${encodeURIComponent(tenantId)}&course_id=${encodeURIComponent(courseId)}&course_level_id=${encodeURIComponent(courseLevelId)}`,
  );
  if (!res.ok) throw new Error("We couldn't load batches. Please try again.");
  return res.json();
}

export const listBatches = (courseId?: string, courseLevelId?: string) =>
  jsonRequest<Batch[]>(
    `/api/v1/batches${courseId || courseLevelId ? `?${new URLSearchParams({
      ...(courseId ? { course_id: courseId } : {}),
      ...(courseLevelId ? { course_level_id: courseLevelId } : {}),
    }).toString()}` : ""}`,
    "GET",
  );

export const createBatch = (
  courseId: string,
  courseLevelId: string,
  name: string,
  examSession?: string,
) =>
  jsonRequest<Batch>("/api/v1/batches", "POST", {
    course_id: courseId,
    course_level_id: courseLevelId,
    name,
    exam_session: examSession || null,
  });

export const updateBatch = (id: string, patch: { name?: string; status?: string }) =>
  jsonRequest<Batch>(`/api/v1/batches/${id}`, "PATCH", patch);

export const listBatchMembers = (id: string) =>
  jsonRequest<BatchMember[]>(`/api/v1/batches/${id}/members`, "GET");

export const listEligibleBatchStudents = (id: string) =>
  jsonRequest<{ id: string; full_name?: string | null }[]>(
    `/api/v1/batches/${id}/eligible-students`,
    "GET",
  );

export const listEligibleBatchTeachers = (id: string) =>
  jsonRequest<{ id: string; full_name?: string | null }[]>(
    `/api/v1/batches/${id}/eligible-teachers`,
    "GET",
  );

export const addBatchMember = (
  id: string,
  profileId: string,
  membershipRole: "student" | "teacher" = "student",
) => jsonRequest<BatchMember>(`/api/v1/batches/${id}/members`, "POST", {
  profile_id: profileId,
  membership_role: membershipRole,
});

export const removeBatchMember = (id: string, profileId: string) =>
  jsonRequest<{ deactivated: boolean }>(`/api/v1/batches/${id}/members/${profileId}`, "DELETE");

export const listAssignments = (quizSetId: string) =>
  jsonRequest<QuizAssignment[]>(`/api/v1/quiz-sets/${quizSetId}/assignments`, "GET");

export const listEligibleBatches = (quizSetId: string) =>
  jsonRequest<Batch[]>(`/api/v1/quiz-sets/${quizSetId}/eligible-batches`, "GET");

export const assignToBatches = (
  quizSetId: string,
  batchIds: string[],
  window?: { from?: string | null; to?: string | null },
) =>
  jsonRequest<{ quiz_set_id: string; audience_mode: string; assignments: QuizAssignment[] }>(
    `/api/v1/quiz-sets/${quizSetId}/assignments`,
    "POST",
    { batch_ids: batchIds, available_from: window?.from ?? null, available_to: window?.to ?? null },
  );

export const withdrawAssignment = (quizSetId: string, batchId: string) =>
  jsonRequest<{ withdrawn: boolean }>(
    `/api/v1/quiz-sets/${quizSetId}/assignments/${batchId}`,
    "DELETE",
  );

// --- Exam scoring standards per course level (Phase 6.2-5) ---
export type ScoringPreset = { key: string; name: string; description: string };
export type CourseExamStandard = {
  course_id: string;
  course_name: string;
  course_level_id: string;
  level_name: string;
  preset_key: string | null;
};

export const listScoringPresets = () =>
  jsonRequest<ScoringPreset[]>("/api/v1/scoring-presets", "GET");

export const listExamStandards = () =>
  jsonRequest<CourseExamStandard[]>("/api/v1/exam-standards", "GET");

export const setExamStandard = (courseLevelId: string, presetKey: string | null) =>
  jsonRequest<{ preset_key: string | null }>(
    `/api/v1/exam-standards/${courseLevelId}`,
    "PUT",
    { preset_key: presetKey },
  );

export type ScoringPolicy = {
  id: string;
  name: string;
  rules: {
    wrong_penalty?: number;
    penalty_is_fraction?: boolean;
    omission_score?: number;
    multi_mode?: "all_or_nothing" | "mrm_partial";
    clamp_negative_total?: boolean;
  };
  created_at: string;
};

export const listScoringPolicies = () =>
  jsonRequest<ScoringPolicy[]>("/api/v1/scoring-policies", "GET");

export const createScoringPolicy = (input: {
  name: string;
  wrong_penalty: number;
  penalty_is_fraction: boolean;
  omission_score: number;
  multi_mode: "all_or_nothing" | "mrm_partial";
  clamp_negative_total: boolean;
}) => jsonRequest<ScoringPolicy>("/api/v1/scoring-policies", "POST", input);

export const setQuizScoringPolicy = (quizSetId: string, policyId: string | null) =>
  jsonRequest<{ quiz_set_id: string; scoring_policy_id: string | null }>(
    `/api/v1/quiz-sets/${quizSetId}/scoring-policy`,
    "PUT",
    { policy_id: policyId },
  );

// --- Commerce paper profiles per course level (Phase 6.3-D) ---
export type PaperProfileFields = {
  exam_body: string | null;
  level: string | null;
  paper: string | null;
  assessment_year: string | null;
  framework: string | null;
};
export type CoursePaperProfile = {
  course_id: string;
  course_name: string;
  course_level_id: string;
  level_name: string;
  profile: PaperProfileFields | null;
};

export const listPaperProfiles = () =>
  jsonRequest<CoursePaperProfile[]>("/api/v1/paper-profiles", "GET");

export const setPaperProfile = (courseLevelId: string, fields: PaperProfileFields) =>
  jsonRequest<{ profile: PaperProfileFields | null }>(
    `/api/v1/paper-profiles/${courseLevelId}`,
    "PUT",
    fields,
  );

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
  level_name: string;
  chapters: number;
  quizzes_total: number;
  quizzes_published: number;
  quizzes_draft: number;
  questions: number;
  pending_review: number;
  needs_edit: number;
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

export type DirectoryPage = {
  items: AdminUser[];
  page: number;
  page_size: number;
  total: number;
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

export const listUsers = (page = 1, query = "") =>
  jsonRequest<DirectoryPage>(
    `/api/v1/users?page=${page}&page_size=12&q=${encodeURIComponent(query)}`,
    "GET",
  );
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

export type CourseImpact = {
  subjects: number;
  students: number;
  teacher_assignments: number;
  quiz_sets: number;
  documents: number;
};
export const getCourseImpact = (courseId: string) =>
  jsonRequest<CourseImpact>(`/api/v1/admin/courses/${courseId}/impact`, "GET");
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
  pipeline: { pending_review: number; approved: number; rejected: number; needs_edit: number };
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
  pipeline: { pending_review: number; approved: number; rejected: number; needs_edit: number };
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
  courses: string[];
  course_count: number;
  level_count: number;
  subject_count: number;
  logo_url: string | null;
  logo_filename: string | null;
  primary_color: string;
  feature_flags: InstitutionFeatureFlags;
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
  logo_data?: string;
  logo_content_type?: string;
  logo_filename?: string;
  catalog_subject_ids?: string[];
  primary_color?: string;
};
export const onboardInstitution = (input: OnboardInstitutionInput) =>
  jsonRequest<{ created: boolean; tenant_id: string }>(
    "/api/v1/platform/tenants",
    "POST",
    input,
  );

export type InstitutionUpdateInput = {
  name?: string;
  subdomain?: string;
  plan_tier?: "free" | "starter" | "growth" | "enterprise";
  is_active?: boolean;
  logo_data?: string;
  logo_content_type?: string;
  logo_filename?: string;
  primary_color?: string;
};
export type InstitutionDetails = {
  id: string;
  name: string;
  subdomain: string;
  plan_tier: string;
  is_active: boolean;
  created_at: string | null;
  logo_url: string | null;
  logo_filename: string | null;
  primary_color: string;
  feature_flags: InstitutionFeatureFlags;
};
export type InstitutionOfferingSubject = {
  id: string;
  name: string;
};
export type InstitutionOfferingLevel = {
  id: string;
  name: string;
  subjects: InstitutionOfferingSubject[];
};
export type InstitutionOfferingCourse = {
  id: string;
  name: string;
  levels: InstitutionOfferingLevel[];
};
export type InstitutionOfferings = {
  tenant_id: string;
  courses: InstitutionOfferingCourse[];
};
export const getInstitutionOfferings = (id: string) =>
  jsonRequest<InstitutionOfferings>(
    `/api/v1/platform/tenants/${encodeURIComponent(id)}/offerings`,
    "GET",
  );
export const updateInstitution = (id: string, input: InstitutionUpdateInput) =>
  jsonRequest<InstitutionDetails>(`/api/v1/platform/tenants/${id}`, "PATCH", input);

export type InstitutionBranding = {
  tenant_id: string;
  name: string;
  subdomain: string;
  logo_url: string | null;
  primary_color: string;
};
export async function getInstitutionBranding(
  subdomain: string,
): Promise<InstitutionBranding> {
  const response = await apiFetch(
    `${API_BASE}/api/v1/public/institutions/${encodeURIComponent(subdomain)}/branding`,
  );
  if (!response.ok) {
    return apiError(response, "Institution login link not found.");
  }
  return response.json();
}

export type QuestionBankCourse = {
  course: string;
  tenant: string | null;
  questions: number;
  subjects: number;
  chapters: number;
  difficulty: Record<string, number>;
  types: Record<string, number>;
  review_status: ReviewPipelineFull;
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

// --- Super-admin: metadata-only AI API observability ---
export type ApiCallLog = {
  call_type: string;
  provider: "gemini" | "deepseek";
  model: string;
  was_fallback: boolean;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_tokens: number | null;
  thinking_tokens: number | null;
  cost_usd: number | null;
  cost_inr: number | null;
  latency_ms: number;
  status: "success" | "error";
  error_message: string | null;
  created_at: string;
};
export type ApiCallLogPage = { items: ApiCallLog[]; page: number; page_size: number; total: number };
export type ApiLogFilters = {
  page?: number; page_size?: number;
  call_type?: string; provider?: string; status?: string; date_from?: string; date_to?: string;
};
export function listApiLogs(filters: ApiLogFilters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return jsonRequest<ApiCallLogPage>(`/api/v1/platform/api-logs?${params}`, "GET");
}

// --- Super-admin: institution admins ---
export type TenantOption = { id: string; name: string; subdomain: string };
export type InstitutionAdmin = {
  id: string;
  full_name: string | null;
  email: string | null;
  institution: string;
  subdomain: string;
  courses: string[];
  course_count: number;
};
export type AdminCreateInput = {
  full_name: string;
  email: string;
  password: string;
  tenant_id: string;
};

async function listDirectoryPages<T>(path: string): Promise<T[]> {
  const pageSize = 100;
  const items: T[] = [];
  for (let page = 1; ; page += 1) {
    const batch = await jsonRequest<T[]>(
      `${path}?page=${page}&page_size=${pageSize}`,
      "GET",
    );
    items.push(...batch);
    if (batch.length < pageSize) return items;
  }
}

export const listTenants = () => listDirectoryPages<TenantOption>("/api/v1/tenants");
export const listAdmins = () => listDirectoryPages<InstitutionAdmin>("/api/v1/admins");
export const createAdmin = (input: AdminCreateInput) =>
  jsonRequest<{ created: boolean }>("/api/v1/admins", "POST", input);
export const resetAdminTemporaryPassword = (id: string, password: string) =>
  jsonRequest<{ changed: boolean }>(
    `/api/v1/platform/admins/${id}/temporary-password`,
    "POST",
    { password },
  );
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
  needs_edit: number;
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

export type TeacherQuizPerformance = {
  quiz: { id: string; title: string; status: string; published_at: string | null; eligible_students: number };
  summary: {
    eligible_students: number; completed_students: number; not_started_students: number;
    total_attempts: number; average_accuracy: number; highest_accuracy: number; lowest_accuracy: number;
  };
  score_distribution: { label: string; count: number }[];
  students: {
    student_id: string; student_name: string; attempts: number; status: "completed" | "not_started";
    latest_score: number | null; latest_max_score: number | null; latest_accuracy: number | null;
    best_accuracy: number | null; submitted_at: string | null;
  }[];
  question_performance: { question_id: string; question_text: string; answered: number; accuracy: number }[];
};
export const getTeacherQuizPerformance = (quizSetId: string) =>
  jsonRequest<TeacherQuizPerformance>(`/api/v1/teacher/quiz-sets/${quizSetId}/performance`, "GET");

export type PublishedQuizMonitor = {
  quizzes: {
    id: string; title: string; subject: string; published_at: string | null;
    eligible_students: number; completed_students: number; not_started_students: number;
    total_attempts: number; average_accuracy: number; highest_accuracy: number;
    lowest_accuracy: number; last_activity: string | null;
  }[];
};
export const getPublishedQuizMonitor = () =>
  jsonRequest<PublishedQuizMonitor>("/api/v1/teacher/published-quizzes", "GET");

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
export const getAdminQuizSets = (teacherId?: string) => {
  const params = new URLSearchParams();
  if (teacherId) params.set("teacher_id", teacherId);
  return listBoundedPages<AdminQuizSet>("/api/v1/admin/quiz-sets", params);
};

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
  topic_question_limits: Record<string, number>;
  topic_groups?: ExtractedTopicGroup[];
};

export type ExtractedTopicGroup = {
  name: string;
  group_name?: string;
  subtopics: string[];
  page_ranges: { start: number; end: number }[];
  suggested_question_limit: number;
};

/** Extract the teachable topics from an uploaded document (Gemini). ~5-15s. */
export const extractTopics = (documentId: string) =>
  jsonRequest<ExtractedTopics>(`/api/v1/documents/${documentId}/topics`, "POST");

export type TopicWeight = "high" | "medium" | "low";
export type BlueprintTopicInput = {
  name: string;
  weight?: TopicWeight;
  // Per-topic blueprint: exact per-format counts for this topic, e.g.
  // { mcq_single: 2, fill_blank: 1 }. When any topic sets `counts`, the backend
  // treats the request as per-topic mode (weight ignored, selected topics only).
  counts?: Record<string, number>;
};

export type BlueprintGenerateRequest = {
  document_id: string;
  subject_id: string;
  chapter_name: string;
  selected_topics: BlueprintTopicInput[];
  // Legacy global per-type counts, e.g. { mcq_single: 3, true_false: 2 }.
  // Optional / omitted in per-topic mode (each topic carries its own counts).
  type_counts?: Record<string, number>;
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

/** Prefer durable jobs; older installations use a bounded synchronous fallback. */
export const generateBlueprintQuiz = async (req: BlueprintGenerateRequest) => {
  if ((await listFacultyJobs()).enabled) {
    return submitFacultyGeneration(req);
  }
  return jsonRequest<BlueprintGenerateResponse>(
    "/api/v1/quiz-sets/generate-blueprint",
    "POST",
    req,
    QUIZ_GENERATION_TIMEOUT_MS,
  );
};

// --- Large-document analysis (chunked Map-Reduce) -------------------------
// Route a document by size: a small document returns its topics immediately;
// a large one starts a resumable background analysis job to poll.
export type AnalyzeResponse =
  | {
      mode: "direct";
      document_id: string;
      topics: string[];
      topic_question_limits: Record<string, number>;
      topic_groups?: ExtractedTopicGroup[];
      source_quality_warnings: string[];
    }
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
  topics: ExtractedTopicGroup[];
  quiz_set_id: string | null;
  analysis_mode?: "local_typed_pdf_outline" | "single_call_ai_outline" | null;
  source_quality_warnings: string[];
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
export const generateFromJob = async (
  jobId: string,
  req: Omit<BlueprintGenerateRequest, "document_id"> & { document_id?: string },
) => {
  if (req.document_id && (await listFacultyJobs()).enabled) {
    return submitFacultyGeneration({ ...req, document_id: req.document_id }, jobId);
  }
  return jsonRequest<BlueprintGenerateResponse & { job_id: string }>(
    `/api/v1/quiz-sets/generation-jobs/${jobId}/generate`,
    "POST",
    req,
    QUIZ_GENERATION_TIMEOUT_MS,
  );
};

export type FacultyJob = {
  id: string;
  kind: "blueprint" | "analysis_quiz" | "extraction";
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  phase: string;
  attempts: number;
  error_message: string | null;
  result: { quiz_set_id: string; quiz_status?: string | null } | null;
  created_at: string;
};

export type QueuedFacultyResponse = { background_job: FacultyJob };

export const listFacultyJobs = () =>
  jsonRequest<{ enabled: boolean; jobs: FacultyJob[] }>("/api/v1/faculty-jobs", "GET");

export const cancelFacultyJob = (id: string) =>
  jsonRequest<FacultyJob>(`/api/v1/faculty-jobs/${id}/cancel`, "POST");

async function submitFacultyGeneration(req: BlueprintGenerateRequest, analysisJobId?: string): Promise<QueuedFacultyResponse> {
  const body = { ...req, request_key: crypto.randomUUID(), analysis_job_id: analysisJobId };
  let job: FacultyJob;
  try {
    job = await jsonRequest<FacultyJob>("/api/v1/faculty-jobs", "POST", body);
  } catch (error) {
    if (!(error instanceof ApiRequestError) || !["network_error", "request_timeout"].includes(error.code)) throw error;
    // A lost acknowledgement is retried with the SAME intent key.
    job = await jsonRequest<FacultyJob>("/api/v1/faculty-jobs", "POST", body);
  }
  window.dispatchEvent(new Event("faculty-job-queued"));
  return { background_job: job };
}

export type QueuedFinalGeneration = { job_id: string; status: string; created: boolean };
export const queueBlueprintQuizGeneration = async (
  req: BlueprintGenerateRequest,
): Promise<QueuedFinalGeneration | QueuedFacultyResponse> => {
  if ((await listFacultyJobs()).enabled) return submitFacultyGeneration(req);
  return jsonRequest<QueuedFinalGeneration>(
    "/api/v1/quiz-sets/generate-blueprint/async", "POST", req,
  );
};
export const queueGenerationFromJob = async (
  jobId: string,
  req: Omit<BlueprintGenerateRequest, "document_id"> & { document_id: string },
): Promise<QueuedFinalGeneration | QueuedFacultyResponse> => {
  if ((await listFacultyJobs()).enabled) {
    return submitFacultyGeneration(req, jobId);
  }
  const legacyRequest = {
    subject_id: req.subject_id,
    chapter_name: req.chapter_name,
    selected_topics: req.selected_topics,
    type_counts: req.type_counts,
    cognitive_level: req.cognitive_level,
    difficulty: req.difficulty,
  };
  return jsonRequest<QueuedFinalGeneration>(
    `/api/v1/quiz-sets/generation-jobs/${jobId}/generate-async`,
    "POST",
    legacyRequest,
  );
};

export type DuplicateCheck = {
  duplicate: boolean;
  previous_filename?: string | null;
  previous_uploaded_at?: string | null;
};

/** Non-blocking warning: is the SAME file already filed under this SAME subject
 * + chapter? Called at the "Extract topics" step; the caller proceeds either
 * way and only surfaces a warning banner when `duplicate` is true. */
export const checkDocumentDuplicate = (
  documentId: string,
  subjectId: string,
  chapterName: string,
) =>
  jsonRequest<DuplicateCheck>("/api/v1/documents/check-duplicate", "POST", {
    document_id: documentId,
    subject_id: subjectId,
    chapter_name: chapterName,
  });
