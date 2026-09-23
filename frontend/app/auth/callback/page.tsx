"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Brand } from "@/components/ui/brand";
import { listPublicCourses, PublicCourse, warmBackend } from "@/lib/api";
import {
  dashboardDestination,
  isDashboardRole,
  writeDashboardBootstrap,
} from "@/lib/dashboard-bootstrap";
import { PENDING_GOOGLE_COURSE_KEY } from "@/lib/google-auth";
import { PENDING_GOOGLE_LEVEL_KEY } from "@/lib/google-auth";
import { PENDING_AUTH_NEXT_KEY } from "@/lib/google-auth";
import { PENDING_GOOGLE_TENANT_KEY } from "@/lib/google-auth";
import { createClient } from "@/lib/supabase";
import { PUBLIC_ENV } from "@/lib/public-env";
import { safeDashboardNext } from "@/lib/safe-next";

export default function AuthCallbackPage() {
  const router = useRouter();
  const initialized = useRef(false);
  const [courses, setCourses] = useState<PublicCourse[]>([]);
  const [courseId, setCourseId] = useState("");
  const [courseLevelId, setCourseLevelId] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const defaultTenantId = PUBLIC_ENV.defaultTenantId;

  const finishDestination = useCallback(() => {
    const destination = safeDashboardNext(
      window.sessionStorage.getItem(PENDING_AUTH_NEXT_KEY),
    );
    window.sessionStorage.removeItem(PENDING_AUTH_NEXT_KEY);
    return destination;
  }, []);

  const completeGoogleSignup = useCallback(async (
    selectedCourseId: string,
    selectedLevelId: string,
  ) => {
    setSaving(true);
    setError(null);
    const supabase = createClient();
    const { error: completionError } = await supabase.rpc(
      "complete_google_signup",
      {
        p_course_id: selectedCourseId,
        p_course_level_id: selectedLevelId,
      },
    );
    if (completionError) {
      console.error("Google student signup completion failed", {
        code: completionError.code ?? "unknown",
      });
      setError(
        "We couldn't finish setting up your student account. Please try again or contact your institution.",
      );
      setSaving(false);
      return;
    }
    window.sessionStorage.removeItem(PENDING_GOOGLE_COURSE_KEY);
    window.sessionStorage.removeItem(PENDING_GOOGLE_LEVEL_KEY);
    window.sessionStorage.removeItem(PENDING_GOOGLE_TENANT_KEY);
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session?.user) throw new Error("Sign-up did not create a session.");
    writeDashboardBootstrap(session.user.id, "student", false);
    warmBackend();
    router.replace(dashboardDestination("student", finishDestination()));
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

        // exchangeCodeForSession has already authenticated and persisted the
        // session. Reuse it locally instead of making an immediate duplicate
        // Auth-server request; the following RLS query validates access.
        const {
          data: { session },
          error: sessionError,
        } = await supabase.auth.getSession();
        if (sessionError) throw sessionError;
        const user = session?.user;
        if (!user) throw new Error("Google sign-in did not create a session.");

        const { data: profile, error: profileError } = await supabase
          .from("profiles")
          .select("id,role,must_change_password")
          .eq("id", user.id)
          .maybeSingle();
        if (profileError) throw profileError;

        // Existing password or Google users already have an authoritative
        // profile. Automatic identity linking therefore preserves their role,
        // tenant, and enrollments and can go straight to the dashboard.
        if (profile) {
          if (!isDashboardRole(profile.role)) {
            throw new Error("Account profile has an unsupported role.");
          }
          window.sessionStorage.removeItem(PENDING_GOOGLE_COURSE_KEY);
          window.sessionStorage.removeItem(PENDING_GOOGLE_LEVEL_KEY);
          window.sessionStorage.removeItem(PENDING_GOOGLE_TENANT_KEY);
          writeDashboardBootstrap(
            user.id,
            profile.role,
            Boolean(profile.must_change_password),
          );
          warmBackend();
          router.replace(
            dashboardDestination(profile.role, finishDestination()),
          );
          router.refresh();
          return;
        }

        const tenantId =
          window.sessionStorage.getItem(PENDING_GOOGLE_TENANT_KEY) ||
          defaultTenantId;
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
        const pendingLevelId = window.sessionStorage.getItem(
          PENDING_GOOGLE_LEVEL_KEY,
        );
        const pendingCourse = availableCourses.find((c) => c.id === pendingCourseId);
        if (
          pendingCourse &&
          pendingLevelId &&
          pendingCourse.levels.some((level) => level.id === pendingLevelId)
        ) {
          setCourseId(pendingCourse.id);
          setCourseLevelId(pendingLevelId);
          setLoading(false);
          await completeGoogleSignup(pendingCourse.id, pendingLevelId);
          return;
        }

        window.sessionStorage.removeItem(PENDING_GOOGLE_COURSE_KEY);
        window.sessionStorage.removeItem(PENDING_GOOGLE_LEVEL_KEY);
        setLoading(false);
      } catch {
        setError("Google sign-in could not be completed. Please try again.");
        setLoading(false);
      }
    }

    void finishOAuth();
  }, [completeGoogleSignup, defaultTenantId, finishDestination, router]);

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
                Pick your course and level to finish setting up your student account.
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
                  onChange={(event) => {
                    setCourseId(event.target.value);
                    setCourseLevelId("");
                  }}
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
              <label className="block text-sm font-medium text-foreground">
                Level
                <select
                  className="mt-2 h-11 w-full rounded-lg border border-input bg-background px-3 text-sm"
                  value={courseLevelId}
                  onChange={(event) => setCourseLevelId(event.target.value)}
                  disabled={!courseId}
                >
                  <option value="">
                    {courseId ? "Select your level…" : "Select a course first…"}
                  </option>
                  {(courses.find((course) => course.id === courseId)?.levels ?? []).map((level) => (
                    <option key={level.id} value={level.id}>{level.name}</option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="w-full rounded-xl bg-emerald-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={!courseId || !courseLevelId}
                onClick={() => completeGoogleSignup(courseId, courseLevelId)}
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
