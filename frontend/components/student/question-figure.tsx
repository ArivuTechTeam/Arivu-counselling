"use client";

import { useEffect, useState } from "react";

import { fetchFigureObjectUrl } from "@/lib/api";

/**
 * Renders a question's source-document figure for a STUDENT.
 *
 * The image is fetched from the authenticated same-origin proxy
 * (`GET /api/v1/figures/{id}`) with the caller's bearer token and shown as a
 * `blob:` URL — so it never depends on an expiring signed URL during a long
 * attempt, and a student can only load figures from their own tenant.
 *
 * Renders nothing when there is no figure or the fetch fails (a missing diagram
 * must never block answering the question).
 */
export function QuestionFigure({ figureId }: { figureId?: string | null }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!figureId) return;
    let active = true;
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);
    fetchFigureObjectUrl(figureId)
      .then((u) => {
        if (active) {
          objectUrl = u;
          setUrl(u);
        } else {
          URL.revokeObjectURL(u); // component unmounted before the fetch resolved
        }
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [figureId]);

  if (!figureId || failed) return null;
  if (!url) {
    return (
      <div
        className="my-3 h-40 w-full max-w-md animate-pulse rounded-lg border bg-muted/40"
        aria-hidden="true"
      />
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt="Question figure"
      className="my-3 max-h-72 w-auto rounded-lg border bg-white object-contain"
    />
  );
}
