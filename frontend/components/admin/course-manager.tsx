"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { AlertTriangle, BookOpen, Inbox, Trash, X } from "@/components/ui/icons";
import {
  Course,
  createCourse,
  createSubject,
  deleteCourse,
  deleteSubject,
  listCourses,
} from "@/lib/api";

// --- per-course colour (auto-assigned — backend has no colour field) ---------
const PALETTE = [
  "#2E8857",
  "#6366f1",
  "#0ea5e9",
  "#f59e0b",
  "#ec4899",
  "#10b981",
  "#8b5cf6",
  "#f43f5e",
];
function courseColor(id: string): string {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .slice(0, 2)
      .map((w) => w[0])
      .join("")
      .toUpperCase() || "?"
  );
}

// --- tiny UI kit --------------------------------------------------------------
const solidBtn =
  "inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-bold text-primary-foreground transition hover:opacity-90 disabled:opacity-50";
const ghostBtn =
  "inline-flex items-center gap-1.5 rounded-lg border border-input px-4 py-2 text-sm font-semibold text-foreground transition hover:bg-secondary disabled:opacity-50";
const field =
  "h-11 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

function Spinner() {
  return (
    <div className="mx-auto my-12 h-9 w-9 animate-spin rounded-full border-[3px] border-muted border-t-primary" />
  );
}

function EmptyState({
  icon,
  title,
  action,
}: {
  icon: ReactNode;
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-border bg-card p-12 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        {icon}
      </span>
      <p className="max-w-xs text-sm text-muted-foreground">{title}</p>
      {action}
    </div>
  );
}

/** Styled inline error row — tinted bg + warning icon. */
function ErrorRow({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

function Modal({
  title,
  onClose,
  children,
  footer,
  maxW = "max-w-md",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  maxW?: string;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className={`animate-rise w-full ${maxW} rounded-[18px] border border-border bg-card p-7 shadow-2xl`}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-extrabold text-foreground">{title}</h3>
          <button
            onClick={onClose}
            className="leading-none text-muted-foreground transition hover:text-foreground"
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>
        {children}
        {footer && <div className="mt-6 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

// --- cards --------------------------------------------------------------------
function CourseCard({
  course,
  onOpen,
  onDelete,
}: {
  course: Course;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const color = courseColor(course.id);
  const n = course.subjects.length;
  return (
    <div className="animate-rise relative overflow-hidden rounded-[14px] border-[1.5px] border-border bg-card shadow-[0_2px_8px_rgba(16,40,28,0.04)] transition hover:-translate-y-0.5 hover:shadow-[0_8px_26px_rgba(15,23,42,0.12)]">
      <button
        type="button"
        onClick={onDelete}
        aria-label={`Delete ${course.name}`}
        className="absolute right-3 top-4 z-10 inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive"
      >
        <Trash size={16} />
      </button>
      <button type="button" onClick={onOpen} className="block w-full text-left">
        <div className="h-1.5" style={{ background: color }} />
        <div className="p-5 pr-14">
        <div className="flex items-center gap-3">
          <span
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[14px] text-base font-black text-white"
            style={{ background: color, boxShadow: `0 4px 12px ${color}44` }}
          >
            {initials(course.name)}
          </span>
          <div className="min-w-0">
            <p className="truncate text-[0.98rem] font-extrabold text-foreground">
              {course.name}
            </p>
            <p className="text-xs text-muted-foreground">
              {n} subject{n === 1 ? "" : "s"}
            </p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <span
            className="rounded-full px-2.5 py-0.5 text-[0.7rem] font-bold"
            style={{ background: `${color}18`, color, border: `1px solid ${color}33` }}
          >
            {n} subject{n === 1 ? "" : "s"}
          </span>
          <span className="inline-flex items-center gap-1 text-[0.72rem] font-semibold text-muted-foreground">
            View subjects <span aria-hidden="true">→</span>
          </span>
        </div>
        </div>
      </button>
    </div>
  );
}

function SubjectCard({
  name,
  color,
  onDelete,
}: {
  name: string;
  color: string;
  onDelete: () => void;
}) {
  return (
    <div className="animate-rise relative overflow-hidden rounded-[14px] border-[1.5px] border-border bg-card shadow-[0_2px_8px_rgba(16,40,28,0.04)] transition-shadow hover:shadow-[0_6px_24px_rgba(15,23,42,0.10)]">
      <button
        type="button"
        onClick={onDelete}
        aria-label={`Delete ${name}`}
        className="absolute right-3 top-3 z-10 inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive"
      >
        <Trash size={16} />
      </button>
      <div className="h-1" style={{ background: color }} />
      <div className="min-h-20 p-4 pr-14">
        <p className="break-words text-[0.97rem] font-bold text-foreground">{name}</p>
      </div>
    </div>
  );
}

type DeleteTarget = { kind: "course" | "subject"; id: string; name: string };

function DeleteModal({
  target,
  busy,
  onCancel,
  onConfirm,
}: {
  target: DeleteTarget;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Modal title="" onClose={onCancel} maxW="max-w-sm">
      <div className="flex flex-col items-center gap-3 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <Trash size={24} />
        </div>
        <h3 className="text-base font-extrabold text-foreground">
          Delete {target.kind} &ldquo;{target.name}&rdquo;?
        </h3>
        <p className="text-sm text-muted-foreground">
          {target.kind === "course" ? "This removes the course and its subjects. " : ""}
          <span className="font-bold text-destructive">This cannot be undone.</span>
        </p>
        <div className="mt-3 flex gap-2">
          <button className={ghostBtn} onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-destructive px-4 py-2 text-sm font-bold text-destructive-foreground transition hover:opacity-90 disabled:opacity-50"
          >
            <Trash size={15} />
            {busy ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// --- main ---------------------------------------------------------------------
export function CourseManager() {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [openCourseId, setOpenCourseId] = useState<string | null>(null);
  const [modal, setModal] = useState<"course" | "subject" | null>(null);
  const [name, setName] = useState("");
  const [del, setDel] = useState<DeleteTarget | null>(null);

  function refresh() {
    listCourses()
      .then(setCourses)
      .catch((e) => setError(e.message));
  }
  useEffect(refresh, []);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const openCourse = useMemo(
    () => (courses ?? []).find((c) => c.id === openCourseId) ?? null,
    [courses, openCourseId],
  );

  function closeModal() {
    setModal(null);
    setName("");
  }
  async function submitModal() {
    const v = name.trim();
    if (!v) return;
    if (modal === "course") {
      await run(() => createCourse(v));
    } else if (modal === "subject" && openCourseId) {
      await run(() => createSubject(openCourseId, v));
    }
    closeModal();
  }
  async function confirmDelete() {
    if (!del) return;
    const t = del;
    setDel(null);
    if (t.kind === "course") {
      if (openCourseId === t.id) setOpenCourseId(null);
      await run(() => deleteCourse(t.id));
    } else {
      await run(() => deleteSubject(t.id));
    }
  }

  // ---- drilled-in: subjects of one course ----
  if (openCourse) {
    const color = courseColor(openCourse.id);
    const subs = openCourse.subjects;
    return (
      <div className="flex flex-col gap-5">
        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <button
            onClick={() => setOpenCourseId(null)}
            className="font-semibold text-primary hover:underline"
          >
            Courses
          </button>
          <span>›</span>
          <span className="font-bold text-foreground">{openCourse.name}</span>
        </div>

        <div
          className="animate-rise flex flex-wrap items-center justify-between gap-4 rounded-[18px] p-6 text-white sm:p-7"
          style={{
            background: `linear-gradient(135deg, ${color}, ${color}cc)`,
            boxShadow: `0 8px 32px ${color}44`,
          }}
        >
          <div className="min-w-0">
            <button
              onClick={() => setOpenCourseId(null)}
              className="text-[0.72rem] font-bold uppercase tracking-[0.1em] text-white/70 transition hover:text-white"
            >
              ← Courses
            </button>
            <h2 className="mt-1 truncate text-xl font-black">{openCourse.name}</h2>
            <p className="mt-1 text-sm text-white/75">
              {subs.length} subject{subs.length === 1 ? "" : "s"}
            </p>
          </div>
          <button
            onClick={() => {
              setName("");
              setModal("subject");
            }}
            className="inline-flex items-center gap-1.5 rounded-xl bg-white/95 px-5 py-2.5 text-sm font-extrabold shadow-md"
            style={{ color }}
          >
            + Add subject
          </button>
        </div>

        {error && <ErrorRow message={error} />}

        {subs.length === 0 ? (
          <EmptyState
            icon={<BookOpen size={22} />}
            title="No subjects yet — add the first subject for this course."
            action={
              <button
                onClick={() => {
                  setName("");
                  setModal("subject");
                }}
                className={solidBtn}
              >
                + Add subject
              </button>
            }
          />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-[repeat(auto-fill,minmax(280px,320px))]">
            {subs.map((sub) => (
              <SubjectCard
                key={sub.id}
                name={sub.name}
                color={color}
                onDelete={() => setDel({ kind: "subject", id: sub.id, name: sub.name })}
              />
            ))}
          </div>
        )}

        {modal === "subject" && (
          <Modal
            title={`Add subject to ${openCourse.name}`}
            onClose={closeModal}
            footer={
              <>
                <button className={ghostBtn} onClick={closeModal} disabled={busy}>
                  Cancel
                </button>
                <button className={solidBtn} onClick={submitModal} disabled={busy || !name.trim()}>
                  {busy ? "Saving…" : "Add subject"}
                </button>
              </>
            }
          >
            <label className="flex flex-col gap-1.5 text-sm font-semibold text-foreground">
              Subject name
              <input
                autoFocus
                className={field}
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submitModal()}
                placeholder="e.g. Accounting"
              />
            </label>
          </Modal>
        )}
        {del && (
          <DeleteModal target={del} busy={busy} onCancel={() => setDel(null)} onConfirm={confirmDelete} />
        )}
      </div>
    );
  }

  // ---- course grid ----
  return (
    <div className="flex flex-col gap-5">
      <div className="animate-rise flex flex-wrap items-center justify-between gap-4 rounded-[18px] bg-gradient-to-br from-[#2E8857] via-[#2a7a52] to-[#245a41] p-6 text-white shadow-[0_10px_32px_rgba(15,23,42,0.18)] sm:p-7">
        <div>
          <p className="text-[0.72rem] font-bold uppercase tracking-[0.1em] text-white/60">
            Hierarchical management
          </p>
          <h2 className="mt-1 text-2xl font-black">Courses &amp; Subjects</h2>
          <p className="mt-1 text-sm text-white/70">Course → Subject</p>
        </div>
        <button
          onClick={() => {
            setName("");
            setModal("course");
          }}
          className="inline-flex items-center gap-1.5 rounded-xl bg-white px-5 py-2.5 text-sm font-extrabold text-[#2E8857] shadow-[0_4px_14px_rgba(0,0,0,0.2)]"
        >
          + Add course
        </button>
      </div>

      {error && <ErrorRow message={error} />}

      {courses === null ? (
        <Spinner />
      ) : courses.length === 0 ? (
        <EmptyState
          icon={<Inbox size={22} />}
          title="No courses yet — add the courses your institution offers (e.g. CA Foundation)."
          action={
            <button
              onClick={() => {
                setName("");
                setModal("course");
              }}
              className={solidBtn}
            >
              + Add your first course
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-[repeat(auto-fill,minmax(280px,320px))]">
          {courses.map((c) => (
            <CourseCard
              key={c.id}
              course={c}
              onOpen={() => setOpenCourseId(c.id)}
              onDelete={() => setDel({ kind: "course", id: c.id, name: c.name })}
            />
          ))}
        </div>
      )}

      {modal === "course" && (
        <Modal
          title="Add course"
          onClose={closeModal}
          footer={
            <>
              <button className={ghostBtn} onClick={closeModal} disabled={busy}>
                Cancel
              </button>
              <button className={solidBtn} onClick={submitModal} disabled={busy || !name.trim()}>
                {busy ? "Saving…" : "Add course"}
              </button>
            </>
          }
        >
          <label className="flex flex-col gap-1.5 text-sm font-semibold text-foreground">
            Course name
            <input
              autoFocus
              className={field}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submitModal()}
              placeholder="e.g. CA Foundation"
            />
          </label>
          <p className="mt-2 text-xs text-muted-foreground">
            Students and teachers pick a course when they sign up.
          </p>
        </Modal>
      )}
      {del && (
        <DeleteModal target={del} busy={busy} onCancel={() => setDel(null)} onConfirm={confirmDelete} />
      )}
    </div>
  );
}
