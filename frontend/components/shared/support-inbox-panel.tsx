"use client";

import { useState, type FormEvent } from "react";
import useSWR from "swr";

import { ContactBrand } from "@/components/shared/contact-brand";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getSupportInbox, replyToStudentContact } from "@/lib/api";

export function SupportInboxPanel({
  role,
  institution,
}: {
  role: "super_admin" | "institution_admin";
  institution: { name: string; logo_url: string | null } | null;
}) {
  const { data: items, error, mutate } = useSWR("support-inbox", getSupportInbox);
  const [activeReference, setActiveReference] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const destination = role === "super_admin" ? "platform" : "institution";

  async function sendReply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeReference || saving || !reply.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      await replyToStudentContact(activeReference, reply.trim());
      setActiveReference(null);
      setReply("");
      await mutate();
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : "We couldn't send the reply.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">Student support inbox</CardTitle>
        <CardDescription>
          {role === "super_admin"
            ? "App feedback and bugs sent to ArivuPro."
            : "Course, account-access, and quiz requests from your students."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ContactBrand destination={destination} institution={institution} />
        {error ? (
          <p role="alert" className="text-sm text-destructive">We could not load the inbox. Please refresh the page.</p>
        ) : !items ? (
          <p className="text-sm text-muted-foreground">Loading requests…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No student requests yet.</p>
        ) : items.map((item) => (
          <article key={item.reference} className="rounded-xl border bg-muted/15 p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-foreground">
                  {item.kind === "feedback" ? "App feedback" : "Support request"} · {item.reference}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.category.replaceAll("_", " ")}
                  {item.institution_name ? ` · ${item.institution_name}` : ""}
                  {item.rating ? ` · ${item.rating}/5` : ""}
                  {` · ${new Date(item.created_at).toLocaleDateString()}`}
                </p>
              </div>
              <span className="rounded-full bg-primary/10 px-2 py-1 text-xs font-medium capitalize text-primary">{item.status}</span>
            </div>
            <p className="mt-3 whitespace-pre-wrap text-sm text-foreground">{item.message}</p>
            {item.reply && (
              <div className="mt-3 rounded-lg border bg-card p-3">
                <p className="text-xs font-semibold text-primary">Last reply</p>
                <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{item.reply}</p>
              </div>
            )}
            {activeReference === item.reference ? (
              <form onSubmit={(event) => void sendReply(event)} className="mt-4 space-y-2">
                <label className="block text-sm font-medium text-foreground">
                  Reply to student
                  <textarea
                    value={reply}
                    onChange={(event) => setReply(event.target.value)}
                    maxLength={4000}
                    required
                    rows={3}
                    className="mt-2 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                </label>
                {saveError && <p role="alert" className="text-sm text-destructive">{saveError}</p>}
                <div className="flex gap-2">
                  <Button type="submit" disabled={saving || !reply.trim()}>{saving ? "Sending…" : "Send reply"}</Button>
                  <Button type="button" variant="outline" disabled={saving} onClick={() => setActiveReference(null)}>Cancel</Button>
                </div>
              </form>
            ) : (
              <Button type="button" variant="outline" size="sm" className="mt-4" onClick={() => {
                setActiveReference(item.reference);
                setReply(item.reply ?? "");
                setSaveError(null);
              }}>
                {item.reply ? "Edit reply" : "Reply"}
              </Button>
            )}
          </article>
        ))}
      </CardContent>
    </Card>
  );
}
