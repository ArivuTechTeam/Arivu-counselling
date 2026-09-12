"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { FileText } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import {
  archiveDocument,
  getDocumentFileUrl,
  reExtractDocument,
} from "@/lib/api";
import { DocumentLogItem } from "@/lib/api";
import { useTeacherDocumentLog } from "@/lib/staff-queries";

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function topicOf(item: DocumentLogItem): string {
  const parts = [item.subject_name, item.chapter_name].filter(Boolean);
  return parts.length ? parts.join(" · ") : "—";
}

type QuizTone = "success" | "warning" | "danger" | "neutral";

// Turn the raw quiz_status into a teacher-friendly label + badge tone.
function quizStatusView(status: string): { label: string; tone: QuizTone } {
  switch (status) {
    case "published":
      return { label: "Published", tone: "success" };
    case "draft":
      return { label: "In review", tone: "warning" };
    case "extracting":
      return { label: "Extracting…", tone: "neutral" };
    case "failed":
      return { label: "Extraction failed", tone: "danger" };
    default:
      return { label: "No quiz yet", tone: "neutral" };
  }
}

export function DocumentLog() {
  const router = useRouter();
  const { data: items = null, error, mutate } = useTeacherDocumentLog();
  const [opening, setOpening] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [archiving, setArchiving] = useState<string | null>(null);

  function load() {
    void mutate();
  }

  async function openDoc(item: DocumentLogItem) {
    // Reserve the tab during the click gesture; opening it after the API await
    // is commonly blocked by mobile and desktop popup protection.
    const documentTab = window.open("about:blank", "_blank");
    if (documentTab) documentTab.opener = null;
    setOpening(item.id);
    setOpenError(null);
    try {
      const { url } = await getDocumentFileUrl(item.id);
      if (documentTab) {
        documentTab.location.replace(url);
      } else {
        window.location.assign(url);
      }
    } catch (e) {
      documentTab?.close();
      setOpenError(
        e instanceof Error ? e.message : "Couldn't open this document. Please try again.",
      );
    } finally {
      setOpening(null);
    }
  }

  // Retry extraction on the already-uploaded file, then open the new draft.
  async function retry(item: DocumentLogItem) {
    setRetrying(item.id);
    setActionError(null);
    try {
      const { quiz_set_id } = await reExtractDocument(item.id);
      router.push(`/dashboard/teacher/review/${quiz_set_id}`);
    } catch (e) {
      setActionError(
        e instanceof Error ? e.message : "Extraction failed again. Please try later.",
      );
      setRetrying(null);
    }
  }

  async function archive(item: DocumentLogItem) {
    if (!window.confirm("Archive this document? Its quizzes and history will be kept.")) {
      return;
    }
    setArchiving(item.id);
    setActionError(null);
    try {
      await archiveDocument(item.id);
      await mutate(
        (current) => current?.filter((document) => document.id !== item.id),
        { revalidate: false },
      );
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Couldn't archive this document.");
    } finally {
      setArchiving(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Document log"
        description="Every file you've uploaded to generate or extract quizzes — newest first."
      />

      {(openError || actionError) && (
        <ErrorCard message={openError || actionError || ""} />
      )}

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Your documents{items ? ` (${items.length})` : ""}</CardTitle>
          <CardDescription>
            Open a document to view the original file you uploaded.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error ? (
            <ErrorCard message={error.message} onRetry={load} />
          ) : items === null ? (
            <SkeletonList rows={5} />
          ) : items.length === 0 ? (
            <EmptyState
              icon={<FileText />}
              title="No documents yet"
              message="Files you upload to generate or extract quizzes will appear here."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="pb-2 pr-3 font-medium">Document</th>
                    <th className="pb-2 pr-3 font-medium">Subject · Chapter</th>
                    <th className="pb-2 pr-3 font-medium">Uploaded</th>
                    <th className="pb-2 pr-3 font-medium">Quiz status</th>
                    <th className="pb-2 text-right font-medium">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {items.map((it) => (
                    <tr key={it.id}>
                      <td className="py-3 pr-3">
                        <div className="flex min-w-0 items-center gap-2">
                          <FileText
                            size={16}
                            className="shrink-0 text-muted-foreground"
                          />
                          <span className="truncate font-medium text-foreground">
                            {it.original_filename || "Untitled document"}
                          </span>
                          {it.file_type && (
                            <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase text-muted-foreground">
                              {it.file_type}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 pr-3 text-muted-foreground">
                        {topicOf(it)}
                      </td>
                      <td className="whitespace-nowrap py-3 pr-3 text-muted-foreground">
                        {formatWhen(it.created_at)}
                      </td>
                      <td className="py-3 pr-3">
                        {(() => {
                          const q = quizStatusView(it.quiz_status);
                          return <Badge tone={q.tone}>{q.label}</Badge>;
                        })()}
                      </td>
                      <td className="py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {it.quiz_status === "failed" && (
                            <button
                              onClick={() => retry(it)}
                              disabled={retrying === it.id}
                              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-60"
                            >
                              {retrying === it.id ? "Retrying…" : "Try again"}
                            </button>
                          )}
                          <button
                            onClick={() => openDoc(it)}
                            disabled={opening === it.id}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-input bg-card px-3 py-1.5 text-xs font-semibold text-foreground shadow-sm transition-colors hover:bg-accent disabled:opacity-60"
                          >
                            {opening === it.id
                              ? "Opening…"
                              : it.file_type === "pdf"
                                ? "Open"
                                : "Download"}
                          </button>
                          <button
                            onClick={() => archive(it)}
                            disabled={archiving === it.id}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-input bg-card px-3 py-1.5 text-xs font-semibold text-muted-foreground transition-colors hover:border-destructive/40 hover:text-destructive disabled:opacity-60"
                          >
                            {archiving === it.id ? "Archiving…" : "Archive"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Documents open via a secure, time-limited link. PDFs open in a new tab;
        Word (DOCX) files download.
      </p>
    </div>
  );
}
