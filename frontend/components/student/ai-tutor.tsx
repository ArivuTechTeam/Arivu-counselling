"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Explanation, explainQuestion } from "@/lib/api";

/**
 * Per-question "Ask AI Tutor" affordance shown on the results screen. First
 * click fetches the cached (or freshly generated) explanation; the student can
 * toggle a detailed vs plain-language version and reveal progressive hints.
 */
export function AiTutor({ questionId }: { questionId: string }) {
  const [data, setData] = useState<Explanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"detail" | "simple">("detail");
  const [showHints, setShowHints] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await explainQuestion(questionId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load explanation");
    } finally {
      setLoading(false);
    }
  }

  if (!data) {
    return (
      <div className="mt-3">
        <Button size="sm" variant="outline" onClick={load} disabled={loading}>
          {loading ? "Thinking…" : "✨ Ask AI Tutor"}
        </Button>
        {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-md border border-brand-200 bg-brand-50 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-brand-700">
          AI Tutor
        </span>
        <div className="ml-auto flex gap-1">
          {(["detail", "simple"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
                mode === m
                  ? "bg-brand-600 text-white"
                  : "text-brand-700 hover:bg-brand-100"
              }`}
            >
              {m === "detail" ? "Detailed" : "Simplify"}
            </button>
          ))}
        </div>
      </div>

      <p className="text-sm text-foreground">
        {mode === "detail" ? data.explanation : data.simplified}
      </p>

      {data.hints.length > 0 && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setShowHints((s) => !s)}
            className="text-xs font-medium text-brand-700 hover:underline"
          >
            {showHints ? "Hide hints" : `Show hints (${data.hints.length})`}
          </button>
          {showHints && (
            <ul className="ml-4 mt-1 list-disc text-xs text-muted-foreground">
              {data.hints.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
