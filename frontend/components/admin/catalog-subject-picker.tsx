"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { AlertTriangle, BookOpen, Search, X } from "@/components/ui/icons";
import {
  CatalogCourse,
  getCourseCatalog,
  provisionCatalogSubjects,
} from "@/lib/api";

export type CatalogProvisionSummary = {
  provisioned: number;
  collisions: string[];
};

export function CatalogSubjectPicker({
  tenantId,
  title = "Add from catalogue",
  cancelLabel = "Cancel",
  onClose,
  onComplete,
}: {
  tenantId?: string;
  title?: string;
  cancelLabel?: string;
  onClose: () => void;
  onComplete: (summary: CatalogProvisionSummary) => void | Promise<void>;
}) {
  const catalog = useSWR(
    ["course-catalog", tenantId ?? "current-tenant"],
    () => getCourseCatalog(tenantId),
  );
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return catalog.data ?? [];
    return (catalog.data ?? [])
      .map((course) => {
        const courseMatches = `${course.code} ${course.name}`
          .toLowerCase()
          .includes(needle);
        const levels = course.levels
          .map((level) => {
            const levelMatches = level.name.toLowerCase().includes(needle);
            const subjects =
              courseMatches || levelMatches
                ? level.subjects
                : level.subjects.filter((subject) =>
                    subject.name.toLowerCase().includes(needle),
                  );
            return { ...level, subjects };
          })
          .filter((level) => level.subjects.length > 0);
        return { ...course, levels };
      })
      .filter((course) => course.levels.length > 0);
  }, [catalog.data, query]);

  function selectableIds(course: CatalogCourse): string[] {
    return course.levels.flatMap((level) =>
      level.subjects.filter((subject) => !subject.offered).map((subject) => subject.id),
    );
  }

  function toggleMany(ids: string[]) {
    setSelected((current) => {
      const next = new Set(current);
      const shouldSelect = ids.some((id) => !next.has(id));
      ids.forEach((id) => (shouldSelect ? next.add(id) : next.delete(id)));
      return next;
    });
  }

  async function confirm() {
    if (selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const summary = await provisionCatalogSubjects(Array.from(selected), tenantId);
      await catalog.mutate();
      await onComplete(summary);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not add catalogue subjects.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      onClose={busy ? undefined : onClose}
      ariaLabelledBy="catalog-picker-title"
      contentClassName="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border bg-card shadow-2xl"
    >
      <div className="flex items-start justify-between gap-4 border-b p-5">
        <div>
          <h2 id="catalog-picker-title" className="text-xl font-extrabold text-foreground">
            {title}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Choose by course and level. Items already added are checked and locked.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          disabled={busy}
          aria-label="Close catalogue picker"
          className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
        >
          <X size={20} />
        </button>
      </div>

      <div className="border-b p-4">
        <label className="relative block">
          <Search size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <span className="sr-only">Search catalogue</span>
          <input
            data-dialog-initial-focus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search courses, levels, or subjects"
            className="h-10 w-full rounded-lg border bg-background pl-10 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
          />
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
        {(error ?? catalog.error?.message) && (
          <div className="mb-4 flex gap-2 rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertTriangle size={17} className="mt-0.5 shrink-0" />
            <span>{error ?? catalog.error?.message}</span>
          </div>
        )}
        {!catalog.data && !catalog.error ? (
          <div className="py-12 text-center text-sm text-muted-foreground">Loading catalogue…</div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-center text-sm text-muted-foreground">
            <BookOpen size={24} />
            No catalogue subjects match your search.
          </div>
        ) : (
          <div className="space-y-4">
            {filtered.map((course) => {
              const courseIds = selectableIds(course);
              const courseChecked = courseIds.length > 0 && courseIds.every((id) => selected.has(id));
              return (
                <section key={course.id} className="rounded-xl border bg-background">
                  <label className="flex cursor-pointer items-start gap-3 border-b px-4 py-3">
                    <input
                      type="checkbox"
                      checked={courseChecked}
                      disabled={courseIds.length === 0}
                      onChange={() => toggleMany(courseIds)}
                      className="mt-1 h-4 w-4 accent-primary"
                    />
                    <span>
                      <span className="font-extrabold text-foreground">{course.code}</span>
                      <span className="ml-2 text-sm text-muted-foreground">{course.name}</span>
                    </span>
                  </label>
                  <div className="space-y-4 p-4">
                    {course.levels.map((level) => {
                      const levelIds = level.subjects
                        .filter((subject) => !subject.offered)
                        .map((subject) => subject.id);
                      const levelChecked = levelIds.length > 0 && levelIds.every((id) => selected.has(id));
                      return (
                        <div key={level.id}>
                          <label className="mb-2 flex cursor-pointer items-center gap-2 text-sm font-bold text-foreground">
                            <input
                              type="checkbox"
                              checked={levelChecked}
                              disabled={levelIds.length === 0}
                              onChange={() => toggleMany(levelIds)}
                              className="h-4 w-4 accent-primary"
                            />
                            {level.name}
                          </label>
                          <div className="grid gap-2 pl-6 sm:grid-cols-2">
                            {level.subjects.map((subject) => (
                              <label
                                key={subject.id}
                                className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${
                                  subject.offered
                                    ? "cursor-not-allowed bg-muted/60 text-muted-foreground"
                                    : "cursor-pointer hover:border-primary/40"
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={subject.offered || selected.has(subject.id)}
                                  disabled={subject.offered}
                                  onChange={() => toggleMany([subject.id])}
                                  className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
                                />
                                <span>{subject.name}</span>
                                {subject.offered && <span className="ml-auto text-xs">Added</span>}
                              </label>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 p-4">
        <span className="text-sm text-muted-foreground">
          {selected.size} new subject{selected.size === 1 ? "" : "s"} selected
        </span>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button type="button" onClick={() => void confirm()} disabled={busy || selected.size === 0}>
            {busy ? "Adding…" : `Add ${selected.size || "selected"}`}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
