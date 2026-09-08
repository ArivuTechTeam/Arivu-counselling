"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { AlertTriangle, X } from "@/components/ui/icons";
import { QualityFinding } from "@/lib/api";

const TONES = {
  critical: "border-rose-200 bg-rose-50 text-rose-700",
  warn: "border-amber-200 bg-amber-50 text-amber-800",
  good: "border-emerald-200 bg-emerald-50 text-emerald-700",
  info: "border-blue-200 bg-blue-50 text-blue-700",
} satisfies Record<QualityFinding["severity"], string>;

const RANK = { critical: 0, warn: 1, info: 2, good: 3 };

export function AlertBanner({
  findings,
  onAction,
  onDismiss,
}: {
  findings: QualityFinding[];
  onAction: (finding: QualityFinding) => void;
  onDismiss: () => void;
}) {
  const visible = [...findings]
    .sort((a, b) => RANK[a.severity] - RANK[b.severity])
    .filter((finding) => finding.severity === "critical" || finding.severity === "warn")
    .slice(0, 3);

  if (visible.length === 0) return null;

  return (
    <section className="overflow-hidden rounded-2xl border border-amber-200 bg-gradient-to-r from-amber-50 via-white to-rose-50 shadow-sm">
      <div className="flex items-center justify-between gap-4 border-b border-amber-200/70 px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 text-amber-700">
            <AlertTriangle size={20} />
          </span>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-amber-700">
              Immediate action needed
            </p>
            <p className="text-sm text-muted-foreground">
              Start with these items today.
            </p>
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Dismiss alerts"
          onClick={onDismiss}
        >
          <X size={17} />
        </Button>
      </div>

      <div className="grid gap-3 p-4 lg:grid-cols-3">
        {visible.map((finding, index) => (
          <button
            key={`${finding.title}-${index}`}
            type="button"
            onClick={() => onAction(finding)}
            className={`rounded-xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-sm ${TONES[finding.severity]}`}
          >
            <span className="text-[10px] font-bold uppercase tracking-wider">
              {finding.severity === "critical" ? "Critical" : "Improve"}
            </span>
            <strong className="mt-2 block text-sm text-foreground">
              {finding.title}
            </strong>
            <span className="mt-2 block text-xs leading-relaxed text-muted-foreground">
              {finding.detail}
            </span>
            <span className="mt-3 block text-xs font-bold">
              {finding.action_label ?? "View details"} ↗
            </span>
          </button>
        ))}
      </div>

      <div className="border-t border-amber-200/70 px-5 py-3 text-right">
        <Link
          href="/dashboard/institution-admin/analytics#key-findings"
          className="text-sm font-semibold text-primary hover:underline"
        >
          View full findings →
        </Link>
      </div>
    </section>
  );
}
