"use client";

import { useEffect, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonList } from "@/components/ui/skeleton";
import { Inbox, Trophy } from "@/components/ui/icons";
import { formatAnswerValue } from "@/lib/format";
import {
  BookmarkedQuestion,
  RevisionTopic,
  getRevisionTopics,
  listBookmarks,
  markTopicRevised,
  removeBookmark,
} from "@/lib/api";

type Tab = "questions" | "topics";

function topicTone(pct: number) {
  return pct < 40 ? "#ff6b7a" : "#f5a623";
}

function TabButton({
  active,
  onClick,
  title,
  count,
  hint,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  count: number | null;
  hint: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-start gap-0.5 rounded-xl border p-4 text-left transition-all ${
        active
          ? "border-primary bg-primary/10 shadow-sm"
          : "border-input bg-card hover:-translate-y-0.5 hover:border-primary/40 hover:bg-accent"
      }`}
    >
      <span className="flex items-center gap-2">
        <span className={`text-sm font-bold ${active ? "text-primary" : "text-foreground"}`}>
          {title}
        </span>
        {count !== null && (
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
              active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
            }`}
          >
            {count}
          </span>
        )}
      </span>
      <span className="text-xs text-muted-foreground">{hint}</span>
    </button>
  );
}

export default function RevisionPage() {
  const [tab, setTab] = useState<Tab>("questions");
  const [items, setItems] = useState<BookmarkedQuestion[] | null>(null);
  const [topics, setTopics] = useState<RevisionTopic[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  function load() {
    setError(null);
    setItems(null);
    setTopics(null);
    listBookmarks()
      .then(setItems)
      .catch((e) => setError(e.message));
    getRevisionTopics()
      .then(setTopics)
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function remove(id: string) {
    setActionError(null);
    setItems((prev) => (prev ? prev.filter((q) => q.id !== id) : prev));
    try {
      await removeBookmark(id);
    } catch {
      setActionError("Couldn't remove that question — please try again.");
      load();
    }
  }

  async function markRevised(key: string) {
    setActionError(null);
    setTopics((prev) => (prev ? prev.filter((t) => t.key !== key) : prev));
    try {
      await markTopicRevised(key);
    } catch {
      setActionError("Couldn't mark that topic revised — please try again.");
      load();
    }
  }

  if (error) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title="Revision"
          description="Master your weak topics and revisit the questions you saved — clear each one as you go."
        />
        <ErrorCard message={error} onRetry={load} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Revision"
        description="Master your weak topics and revisit the questions you saved — clear each one as you go."
      />

      {/* Two full-width tabs */}
      <div className="grid grid-cols-2 gap-3">
        <TabButton
          active={tab === "questions"}
          onClick={() => setTab("questions")}
          title="Saved questions"
          count={items?.length ?? null}
          hint="Questions you bookmarked"
        />
        <TabButton
          active={tab === "topics"}
          onClick={() => setTab("topics")}
          title="Topic revision"
          count={topics?.length ?? null}
          hint="Weak topics to master"
        />
      </div>

      {actionError && (
        <p className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {actionError}
        </p>
      )}

      {/* --- Questions tab --- */}
      {tab === "questions" &&
        (items === null ? (
          <SkeletonList rows={4} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Inbox size={22} />}
            title="No saved questions yet"
            message="While reviewing a quiz result, tap ☆ Revise on any tricky question and it lands here for later."
            className="animate-rise"
          />
        ) : (
          <div className="flex flex-col gap-3">
            {items.map((q, i) => (
              <Card key={q.id} className="animate-rise">
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <CardTitle className="text-base font-semibold leading-snug">
                      {i + 1}. {q.question_text}
                    </CardTitle>
                    <button
                      onClick={() => remove(q.id)}
                      className="shrink-0 rounded-md border border-input px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-destructive/40 hover:text-destructive"
                    >
                      Remove
                    </button>
                  </div>
                  {q.difficulty && (
                    <CardDescription className="capitalize">
                      {q.difficulty}
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="flex flex-col gap-1 text-sm">
                  {q.options && q.options.length > 0 && (
                    <ul className="mb-1 flex flex-col gap-1">
                      {q.options.map((o) => (
                        <li key={o.id} className="text-muted-foreground">
                          <span className="font-mono text-xs">{o.id}.</span> {o.text}
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="font-medium text-emerald-700">
                    Answer: {formatAnswerValue(q.correct_answer)}
                  </p>
                  {q.explanation && (
                    <p className="text-muted-foreground">Why: {q.explanation}</p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        ))}

      {/* --- Topics tab --- */}
      {tab === "topics" &&
        (topics === null ? (
          <SkeletonList rows={4} />
        ) : topics.length === 0 ? (
          <EmptyState
            icon={<Trophy size={22} />}
            title="No weak topics to revise"
            message="Nice work — you're scoring well across your topics. Take more quizzes and any weak spots will show up here to revise."
            className="animate-rise"
          />
        ) : (
          <Card className="animate-rise">
            <CardHeader>
              <CardTitle>Topics to revise</CardTitle>
              <CardDescription>
                Your lowest-scoring topics, weakest first. Revise each, then mark it
                done to clear it from your list.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {topics.map((t) => (
                <div
                  key={t.key}
                  className="flex items-center justify-between gap-3 rounded-lg border p-3"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">
                      {t.topic}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {t.subject} · {t.chapter} · {t.answered} answered
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <span
                      className="text-sm font-semibold"
                      style={{ color: topicTone(t.accuracy) }}
                    >
                      {t.accuracy}%
                    </span>
                    <button
                      onClick={() => markRevised(t.key)}
                      className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
                    >
                      Mark revised
                    </button>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
    </div>
  );
}
