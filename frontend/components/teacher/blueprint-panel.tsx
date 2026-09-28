"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  BlueprintQuestion,
  PaperTypeKey,
  countByType,
  hasClassification,
  mulberry32,
  pickRandomByType,
} from "@/lib/blueprint";

const TYPE_LABEL: Record<PaperTypeKey, string> = {
  pyq: "PYQ",
  mtp: "MTP",
  rtp: "RTP",
  untyped: "Other",
};

const TYPE_TONE: Record<PaperTypeKey, string> = {
  pyq: "border-amber-300 bg-amber-50 text-amber-800",
  mtp: "border-sky-300 bg-sky-50 text-sky-800",
  rtp: "border-violet-300 bg-violet-50 text-violet-800",
  untyped: "border-border bg-muted text-muted-foreground",
};

function clamp(value: number, lo: number, hi: number): number {
  if (Number.isNaN(value)) return lo;
  return Math.max(lo, Math.min(hi, value));
}

export function BlueprintPanel({
  questions,
  publishing,
  previewing,
  onPublish,
  onSelectionChange,
  onPreview,
}: {
  questions: BlueprintQuestion[];
  publishing: boolean;
  previewing: boolean;
  onPublish: (selectedIds: string[]) => void;
  // Reports the current random pick so the page can filter the list to it.
  onSelectionChange: (selectedIds: string[]) => void;
  // Ask the page to show only the selected questions (preview before publish).
  onPreview: () => void;
}) {
  const documentTotal = questions.length;
  const classified = useMemo(() => hasClassification(questions), [questions]);
  const available = useMemo(() => countByType(questions), [questions]);

  // Types the teacher can pick from (present, PYQ/MTP/RTP only).
  const pickTypes = (["pyq", "mtp", "rtp"] as PaperTypeKey[]).filter((t) => available[t] > 0);
  const maxTotal = classified
    ? pickTypes.reduce((sum, t) => sum + available[t], 0)
    : documentTotal;

  // Default: everything selected; the teacher trims down.
  const [wanted, setWanted] = useState(maxTotal);
  const [caps, setCaps] = useState<Record<PaperTypeKey, number>>({
    pyq: available.pyq,
    mtp: available.mtp,
    rtp: available.rtp,
    untyped: classified ? 0 : documentTotal,
  });
  // Re-roll seed. Starts random per session; "Shuffle again" bumps it.
  const [seedBase] = useState(() => Math.floor(Math.random() * 2 ** 31));
  const [shuffleNonce, setShuffleNonce] = useState(0);

  const allocated = classified
    ? pickTypes.reduce((sum, t) => sum + caps[t], 0)
    : caps.untyped;

  const selection = useMemo(
    () => pickRandomByType(questions, caps, mulberry32(seedBase + shuffleNonce)),
    [questions, caps, seedBase, shuffleNonce],
  );

  // Keep the page's copy of the selection in sync (for the "See selected" view).
  // A ref holds the latest callback so this only re-fires when the pick changes.
  const notifyRef = useRef(onSelectionChange);
  notifyRef.current = onSelectionChange;
  useEffect(() => {
    notifyRef.current(selection);
  }, [selection]);

  const matches = allocated === wanted;
  const canPublish = !publishing && allocated >= 1 && matches;

  function setCap(type: PaperTypeKey, raw: string) {
    const next = clamp(parseInt(raw, 10), 0, available[type]);
    setCaps((prev) => ({ ...prev, [type]: next }));
  }

  return (
    <div className="rounded-2xl border bg-card p-4 shadow-sm sm:p-5">
      <div>
        <h2 className="text-base font-semibold tracking-tight">Publish blueprint</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          This document has <strong>{documentTotal}</strong> questions. Choose how many to
          publish — the rest stay saved in your library, nothing is deleted.
        </p>
      </div>

      {/* What the document contains */}
      <div className="mt-4 flex flex-wrap gap-2">
        {(classified ? pickTypes : (["untyped"] as PaperTypeKey[])).map((t) => (
          <span
            key={t}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold ${TYPE_TONE[t]}`}
          >
            {classified ? TYPE_LABEL[t] : "Questions"}
            <span className="tabular-nums opacity-80">{available[t]} available</span>
          </span>
        ))}
      </div>

      {!classified && (
        <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          These questions aren&apos;t tagged PYQ / MTP / RTP, so you can only choose a random
          number. To split by type, re-import the document with{" "}
          <strong>&ldquo;This document contains PYQ / MTP / RTP questions&rdquo;</strong> ticked.
        </p>
      )}

      {/* How many total */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm font-medium text-foreground">
          How many questions do you want?
          <input
            type="number"
            min={1}
            max={maxTotal}
            value={wanted}
            disabled={publishing}
            onChange={(e) => setWanted(clamp(parseInt(e.target.value, 10), 1, maxTotal))}
            className="h-9 w-24 rounded-md border border-input bg-background px-2 text-sm text-foreground"
          />
        </label>
        <span className="text-xs text-muted-foreground">out of {maxTotal}</span>
      </div>

      {/* Per-type split (classified papers only) */}
      {classified && (
        <div className="mt-4 rounded-xl border border-dashed bg-muted/20 p-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            How many of each type? These are picked <strong>at random</strong> from the document.
          </p>
          <div className="flex flex-wrap gap-4">
            {pickTypes.map((t) => (
              <label key={t} className="flex items-center gap-2 text-sm">
                <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${TYPE_TONE[t]}`}>
                  {TYPE_LABEL[t]}
                </span>
                <input
                  type="number"
                  min={0}
                  max={available[t]}
                  value={caps[t]}
                  disabled={publishing}
                  onChange={(e) => setCap(t, e.target.value)}
                  className="h-9 w-16 rounded-md border border-input bg-background px-2 text-sm text-foreground"
                />
                <span className="text-muted-foreground">of {available[t]}</span>
              </label>
            ))}
          </div>
          <p className={`mt-3 text-xs font-medium ${matches ? "text-emerald-700" : "text-amber-700"}`}>
            Allocated {allocated} of {wanted}
            {matches ? " ✓" : allocated < wanted ? ` — ${wanted - allocated} left to assign` : " — too many, reduce a type"}
          </p>
        </div>
      )}

      {/* Preview + actions */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        <p className="text-sm text-muted-foreground">
          {allocated < 1 ? (
            <span className="font-medium text-amber-700">Select at least one question to publish.</span>
          ) : (
            <>
              Publishing a random <strong className="text-foreground">{selection.length}</strong>. The
              other <strong className="text-foreground">{documentTotal - selection.length}</strong> stay
              saved in your library.
            </>
          )}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={onPreview}
            disabled={publishing || allocated < 1}
            className={previewing ? "border-primary/40 bg-primary/10 text-primary" : ""}
            title="Review the exact questions before publishing"
          >
            {previewing ? `Showing selected (${selection.length})` : `See selected (${selection.length})`}
          </Button>
          <Button
            variant="outline"
            onClick={() => setShuffleNonce((n) => n + 1)}
            disabled={publishing || allocated < 1}
            title="Pick a different random set"
          >
            Shuffle again
          </Button>
          <Button onClick={() => onPublish(selection)} disabled={!canPublish}>
            {publishing ? "Publishing…" : `Publish ${selection.length} selected`}
          </Button>
        </div>
      </div>
    </div>
  );
}
