"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Brand } from "@/components/ui/brand";
import { listPublicCourses } from "@/lib/api";
import { PENDING_GOOGLE_COURSE_KEY } from "@/lib/google-auth";
import { createClient } from "@/lib/supabase";

type PublicCourse = { id: string; name: string };

export default function AuthCallbackPage() {
  const router = useRouter();
  const initialized = useRef(false);
  const [courses, setCourses] = useState<PublicCourse[]>([]);
  const [courseId, setCourseId] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tenantId = process.env.NEXT_PUBLIC_DEFAULT_TENANT_ID;

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
    router.replace("/dashboard");
    router.refresh();
  }, [router]);

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
          router.replace("/dashboard");
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
      } catch (e) {
        setError(
          e instanceof Error
            ? e.message
            : "Google sign-in could not be completed. Please try again.",
        );
        setLoading(false);
      }
    }

    void finishOAuth();
  }, [completeGoogleSignup, router, tenantId]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-emerald-50 via-white to-green-50 p-4">
      <section className="w-full max-w-md rounded-2xl border border-emerald-100 bg-white p-7 shadow-xl shadow-emerald-950/10">
        <div className="mb-6 flex justify-center">
          <Brand height={38} />
        </div>

        <h1 className="text-center text-2xl font-semibold text-foreground">
          {loading || saving ? "Finishing Google sign-in" : "Choose your course"}
        </h1>
        <p className="mt-2 text-center text-sm leading-6 text-muted-foreground">
          {loading || saving
            ? "Please wait while we securely prepare your account."
            : "Your course determines your institution. New Google accounts are always created as students."}
        </p>

        {(loading || saving) && (
          <div className="mx-auto mt-7 h-8 w-8 animate-spin rounded-full border-4 border-emerald-100 border-t-emerald-700" aria-label="Loading" />
        )}

        {!loading && !saving && courses.length > 0 && (
          <div className="mt-6 space-y-4">
            <label className="block text-sm font-medium text-foreground">
              Course
              <select
                className="mt-2 h-11 w-full rounded-lg border border-input bg-background px-3 text-sm"
                value={courseId}
                onChange={(event) => setCourseId(event.target.value)}
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

        {!loading && !saving && courses.length === 0 && !error && (
          <p className="mt-6 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
            No courses are available yet. Please contact your institution administrator.
          </p>
        )}

        {error && (
          <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
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
    </main>
  );
}
