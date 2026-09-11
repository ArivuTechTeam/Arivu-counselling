"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Brand } from "@/components/ui/brand";
import { listPublicCourses } from "@/lib/api";
import { PENDING_GOOGLE_COURSE_KEY } from "@/lib/google-auth";
import { PENDING_AUTH_NEXT_KEY } from "@/lib/google-auth";
import { createClient } from "@/lib/supabase";
import { PUBLIC_ENV } from "@/lib/public-env";
import { safeDashboardNext } from "@/lib/safe-next";

type PublicCourse = { id: string; name: string };

export default function AuthCallbackPage() {
  const router = useRouter();
  const initialized = useRef(false);
  const [courses, setCourses] = useState<PublicCourse[]>([]);
  const [courseId, setCourseId] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tenantId = PUBLIC_ENV.defaultTenantId;

  const finishDestination = useCallback(() => {
    const destination = safeDashboardNext(
      window.sessionStorage.getItem(PENDING_AUTH_NEXT_KEY),
    );
    window.sessionStorage.removeItem(PENDING_AUTH_NEXT_KEY);
    return destination;
  }, []);

  const completeGoogleSignup = useCallback(async (selectedCourseId: string) => {
    setSaving(true);
    setError(null);
    const supabase = createClient();
    const { error: completionError } = await supabase.rpc(
      "complete_google_signup",
      { p_course_id: selectedCourseId },
    );
    if (completionError) {
      setError(
        completionError.message ||
          "We couldn't finish setting up your student account. Please try again.",
      );
      setSaving(false);
      return;
    }
    window.sessionStorage.removeItem(PENDING_GOOGLE_COURSE_KEY);
    router.replace(finishDestination());
    router.refresh();
  }, [finishDestination, router]);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    async function finishOAuth() {
      try {
        const url = new URL(window.location.href);
        const providerError =
          url.searchParams.get("error_description") || url.searchParams.get("error");
        if (providerError) throw new Error(providerError);

        const supabase = createClient();
        const code = url.searchParams.get("code");
        if (code) {
          const { error: exchangeError } =
            await supabase.auth.exchangeCodeForSession(code);
          if (exchangeError) throw exchangeError;
          url.searchParams.delete("code");
          window.history.replaceState(
            {},
            "",
            `${url.pathname}${url.search}${url.hash}`,
          );
        }

        const {
          data: { user },
          error: userError,
        } = await supabase.auth.getUser();
        if (userError) throw userError;
        if (!user) throw new Error("Google sign-in did not create a session.");

        const { data: profile, error: profileError } = await supabase
          .from("profiles")
          .select("id")
          .eq("id", user.id)
          .maybeSingle();
        if (profileError) throw profileError;

        // Existing password or Google users already have an authoritative
        // profile. Automatic identity linking therefore preserves their role,
        // tenant, and enrollments and can go straight to the dashboard.
        if (profile) {
          window.sessionStorage.removeItem(PENDING_GOOGLE_COURSE_KEY);
          router.replace(finishDestination());
          router.refresh();
          return;
        }

        if (!tenantId) {
          throw new Error(
            "Institution not configured (missing NEXT_PUBLIC_DEFAULT_TENANT_ID).",
          );
        }

        const availableCourses = await listPublicCourses(tenantId);
        setCourses(availableCourses);
        const pendingCourseId = window.sessionStorage.getItem(
          PENDING_GOOGLE_COURSE_KEY,
        );
        if (pendingCourseId && availableCourses.some((c) => c.id === pendingCourseId)) {
          setCourseId(pendingCourseId);
          setLoading(false);
          await completeGoogleSignup(pendingCourseId);
          return;
        }

        window.sessionStorage.removeItem(PENDING_GOOGLE_COURSE_KEY);
        setLoading(false);
      } catch {
        setError("Google sign-in could not be completed. Please try again.");
        setLoading(false);
      }
    }

    void finishOAuth();
  }, [completeGoogleSignup, finishDestination, router, tenantId]);

  // While exchanging the code / checking for an existing profile, show only a
  // brief, low-ceremony spinner — existing users never see anything past this.
  // `error` implies loading and saving are already both false in every path
  // below, but a failed `completeGoogleSignup` attempt leaves `courses`
  // populated so the course selector stays visible for retry alongside it.
  const isProcessing = loading || saving;
  const needsCourse = !isProcessing && courses.length > 0;
  const noCoursesAvailable = !isProcessing && courses.length === 0 && !error;

  return (
    <div className="fixed inset-0 z-50 flex min-h-screen items-center justify-center bg-muted/40 p-4">
      {isProcessing && (
        <div className="animate-rise flex flex-col items-center gap-3 rounded-2xl bg-card px-8 py-7 shadow-xl">
          <div className="h-7 w-7 animate-spin rounded-full border-4 border-emerald-100 border-t-emerald-700" aria-label="Loading" />
          <p className="text-sm text-muted-foreground">Finishing Google sign-in…</p>
        </div>
      )}

      {(needsCourse || noCoursesAvailable || error) && (
        <section className="animate-rise w-full max-w-sm rounded-2xl bg-card p-6 shadow-xl">
          <div className="mb-4 flex justify-center">
            <Brand height={30} />
          </div>

          {needsCourse && (
            <>
              <h1 className="text-center text-lg font-semibold text-foreground">
                One more step
              </h1>
              <p className="mt-1.5 text-center text-sm leading-6 text-muted-foreground">
                Pick your course to finish setting up your student account.
              </p>
            </>
          )}

          {needsCourse && (
            <div className="mt-5 space-y-3">
              <label className="block text-sm font-medium text-foreground">
                Course
                <select
                  className="mt-2 h-11 w-full rounded-lg border border-input bg-background px-3 text-sm"
                  value={courseId}
                  onChange={(event) => setCourseId(event.target.value)}
                  autoFocus
                >
                  <option value="">Select your course…</option>
                  {courses.map((course) => (
                    <option key={course.id} value={course.id}>
                      {course.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="w-full rounded-xl bg-emerald-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={!courseId}
                onClick={() => completeGoogleSignup(courseId)}
              >
                Continue to dashboard
              </button>
            </div>
          )}

          {noCoursesAvailable && (
            <p className="mt-5 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
              No courses are available yet. Please contact your institution administrator.
            </p>
          )}

          {error && (
            <div className="mt-1 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
              {error}
            </div>
          )}

          {error && (
            <Link
              href="/login"
              className="mt-5 block text-center text-sm font-medium text-emerald-700 hover:underline"
            >
              Return to sign in
            </Link>
          )}
        </section>
      )}
    </div>
  );
}
