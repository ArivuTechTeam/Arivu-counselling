import * as React from "react";

// ArivuPro status / category pill. Tones match the design system exactly:
// emerald = success, amber = warning, rose = danger, warm-neutral = pending/draft.
type BadgeTone = "brand" | "success" | "warning" | "danger" | "neutral" | "type";

const TONE: Record<BadgeTone, string> = {
  brand: "bg-brand-50 text-brand-700",
  success: "bg-emerald-100 text-emerald-700",
  warning: "bg-amber-100 text-amber-700",
  danger: "bg-rose-100 text-rose-700",
  neutral: "bg-muted text-muted-foreground",
  type: "bg-muted text-muted-foreground uppercase tracking-wide",
};

export function Badge({
  tone = "neutral",
  className = "",
  children,
}: {
  tone?: BadgeTone;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${TONE[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

// Map a raw API status string to a tone (shared across questions/quizzes/docs).
export function statusTone(status: string): BadgeTone {
  switch (status) {
    case "approved":
    case "published":
    case "completed":
      return "success";
    case "rejected":
    case "failed":
      return "danger";
    case "needs_edit":
    case "processing":
      return "warning";
    default:
      return "neutral";
  }
}
