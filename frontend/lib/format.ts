/**
 * Display formatters — turn raw API tokens and answer payloads into
 * human-readable text. The golden rule: NEVER leak a snake_cased token or a raw
 * `JSON.stringify({...})` blob into the UI. Everything users see goes through here.
 */

// Friendly labels for snake_cased status tokens (questions, quiz sets, docs…).
const STATUS_LABEL: Record<string, string> = {
  pending_review: "Pending review",
  needs_edit: "Needs edit",
  approved: "Approved",
  rejected: "Rejected",
  published: "Published",
  draft: "Draft",
  archived: "Archived",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
  in_progress: "In progress",
  not_started: "Not started",
  done: "Done",
};

/** "pending_review" → "Pending review". Falls back to Title Case for unknowns. */
export function statusLabel(status: string): string {
  if (!status) return "";
  return (
    STATUS_LABEL[status] ??
    status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

// Friendly labels for the six question types.
const TYPE_LABEL: Record<string, string> = {
  mcq_single: "Single choice",
  mcq_multi: "Multiple choice",
  true_false: "True / False",
  numerical: "Numerical",
  fill_blank: "Fill in the blank",
  matching: "Matching",
};

/** "mcq_single" → "Single choice". */
export function typeLabel(t: string): string {
  return TYPE_LABEL[t] ?? statusLabel(t);
}

// Friendly labels for the three quiz variant (cognitive level) tokens.
const VARIANT_LABEL: Record<string, string> = {
  theory: "Theory",
  practical: "Practical",
  mixed: "Mixed",
};

/** "practical" → "Practical". Falls back to Title Case for unknowns. */
export function variantLabel(v: string | null | undefined): string {
  if (!v) return "Quiz";
  return VARIANT_LABEL[v] ?? statusLabel(v);
}

/**
 * Safely render any answer value (string, number, array, or the various object
 * shapes the API emits) to human text. Never returns raw JSON.
 */
export function formatAnswerValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "(no answer)";
  if (Array.isArray(v)) return v.map(formatAnswerValue).join(", ");

  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    // numerical: { value, tolerance? }
    if ("value" in o) {
      return `${o.value}${o.tolerance ? ` (±${o.tolerance})` : ""}`;
    }
    // fill_blank: { answers: [...] }
    if ("answers" in o && Array.isArray(o.answers)) {
      return (o.answers as unknown[]).map(String).join(" / ");
    }
    // matching: { pairs: [{left,right}, …] }
    if ("pairs" in o && Array.isArray(o.pairs)) {
      return (o.pairs as unknown[])
        .map((p) => {
          const pp = (p ?? {}) as Record<string, unknown>;
          const left = pp.left ?? pp.term ?? pp.key ?? "";
          const right = pp.right ?? pp.match ?? pp.value ?? "";
          return `${left} → ${right}`;
        })
        .join(", ");
    }
    // matching as a plain map: { "A": "1", "B": "2" }
    const entries = Object.entries(o);
    if (entries.length) {
      return entries.map(([k, val]) => `${k} → ${String(val)}`).join(", ");
    }
    return "(no answer)";
  }

  return String(v);
}
