"use client";

import { useState, type FormEvent } from "react";
import useSWR from "swr";

import { ContactBrand } from "@/components/shared/contact-brand";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getMyStudentContacts,
  submitStudentContact,
  type StudentContactCategory,
  type StudentContactKind,
} from "@/lib/api";

const CATEGORY_LABELS: Record<StudentContactCategory, string> = {
  general: "General feedback",
  feature_idea: "Feature idea",
  course_access: "Course or account access",
  quiz_issue: "Quiz or result issue",
  app_bug: "App bug",
};

export function StudentContactPanel({
  institution,
}: {
  institution: { name: string; logo_url: string | null } | null;
}) {
  const { data: requests, error: listError, mutate } = useSWR("my-student-contacts", getMyStudentContacts);
  const [kind, setKind] = useState<StudentContactKind | null>(null);
  const [category, setCategory] = useState<StudentContactCategory>("general");
  const [message, setMessage] = useState("");
  const [rating, setRating] = useState(0);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [reference, setReference] = useState<string | null>(null);

  const destination = kind === "feedback" || category === "app_bug" ? "platform" : "institution";

  function openForm(nextKind: StudentContactKind) {
    setKind(nextKind);
    setCategory(nextKind === "feedback" ? "general" : "course_access");
    setMessage("");
    setRating(0);
    setFormError(null);
    setReference(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!kind || saving) return;
    setSaving(true);
    setFormError(null);
    try {
      const result = await submitStudentContact({
        kind,
        category,
        message: message.trim(),
        rating: kind === "feedback" && rating ? rating : null,
      });
      setReference(result.reference);
      setKind(null);
      await mutate();
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : "We couldn't send this. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="student-help-title" className="space-y-4">
      <div>
        <h2 id="student-help-title" className="text-lg font-semibold text-foreground">Feedback & support</h2>
        <p className="mt-1 text-sm text-muted-foreground">Tell us what could improve, or get help with a problem.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Share app feedback</CardTitle>
            <CardDescription>Ideas and app feedback go to the ArivuPro team.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ContactBrand destination="platform" institution={institution} />
            <Button type="button" onClick={() => openForm("feedback")}>Give feedback</Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Get customer support</CardTitle>
            <CardDescription>Course and quiz help goes to your institution; app bugs go to ArivuPro.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ContactBrand destination="institution" institution={institution} />
            <Button type="button" variant="outline" onClick={() => openForm("support")}>Contact support</Button>
          </CardContent>
        </Card>
      </div>

      {reference && (
        <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
          Sent successfully. Your reference is <span className="font-semibold">{reference}</span>.
        </p>
      )}

      {kind && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">{kind === "feedback" ? "Share app feedback" : "Contact support"}</CardTitle>
            <CardDescription>We use your signed-in account to send updates here. Please do not include passwords or payment details.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={(event) => void submit(event)} className="max-w-2xl space-y-4">
              <label className="block text-sm font-medium text-foreground">
                Topic
                <select
                  value={category}
                  onChange={(event) => setCategory(event.target.value as StudentContactCategory)}
                  className="mt-2 h-11 w-full rounded-lg border border-input bg-background px-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {(kind === "feedback" ? ["general", "feature_idea", "app_bug"] : ["course_access", "quiz_issue", "app_bug"]).map((option) => (
                    <option key={option} value={option}>{CATEGORY_LABELS[option as StudentContactCategory]}</option>
                  ))}
                </select>
              </label>
              <ContactBrand destination={destination} institution={institution} />
              <p className="text-xs text-muted-foreground">
                {destination === "platform" ? "This message will be sent to ArivuPro." : "This message will be sent to your institution administrator."}
              </p>
              {kind === "feedback" && (
                <label className="block text-sm font-medium text-foreground">
                  App rating (optional)
                  <select
                    value={rating}
                    onChange={(event) => setRating(Number(event.target.value))}
                    className="mt-2 h-11 w-full rounded-lg border border-input bg-background px-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <option value={0}>No rating</option>
                    {[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value} / 5</option>)}
                  </select>
                </label>
              )}
              <label className="block text-sm font-medium text-foreground">
                {kind === "feedback" ? "Your feedback" : "Describe the issue"}
                <textarea
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  minLength={10}
                  maxLength={4000}
                  required
                  rows={5}
                  placeholder="Please give enough detail for us to understand, without sharing private credentials."
                  className="mt-2 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </label>
              {formError && <p role="alert" className="text-sm text-destructive">{formError}</p>}
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={saving || message.trim().length < 10}>
                  {saving ? "Sending…" : "Send"}
                </Button>
                <Button type="button" variant="outline" disabled={saving} onClick={() => setKind(null)}>Cancel</Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Your requests</CardTitle>
          <CardDescription>Replies appear here after the team responds.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {listError ? (
            <p role="alert" className="text-sm text-destructive">We could not load your requests. Please refresh the page.</p>
          ) : !requests ? (
            <p className="text-sm text-muted-foreground">Loading requests…</p>
          ) : requests.length === 0 ? (
            <p className="text-sm text-muted-foreground">You have not sent a request yet.</p>
          ) : requests.map((item) => (
            <article key={item.reference} className="rounded-xl border bg-muted/15 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-foreground">{CATEGORY_LABELS[item.category]} · {item.reference}</p>
                <span className="rounded-full bg-primary/10 px-2 py-1 text-xs font-medium capitalize text-primary">{item.status}</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Sent to {item.routed_to === "platform" ? "ArivuPro" : institution?.name ?? "your institution"}
              </p>
              <p className="mt-3 whitespace-pre-wrap text-sm text-foreground">{item.message}</p>
              {item.reply && (
                <div className="mt-3 rounded-lg border bg-card p-3">
                  <p className="text-xs font-semibold text-primary">Support reply</p>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{item.reply}</p>
                </div>
              )}
            </article>
          ))}
        </CardContent>
      </Card>
    </section>
  );
}
