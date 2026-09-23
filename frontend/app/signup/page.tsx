"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { AuthError } from "@supabase/supabase-js";

import { GoogleAuthButton } from "@/components/auth/google-auth-button";
import {
  getInstitutionBranding,
  InstitutionBranding,
  listPublicCourses,
  PublicCourse,
} from "@/lib/api";
import { signInWithGoogle } from "@/lib/google-auth";
import {
  institutionLoginPath,
  institutionSlugFromPath,
  normalizeInstitutionSlug,
} from "@/lib/institution-portal";
import { safeDashboardNext } from "@/lib/safe-next";
import { createClient } from "@/lib/supabase";
import "../login/login.css";

function MailIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  );
}
function LockIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  );
}
function UserIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 4-6 8-6s8 2 8 6" />
    </svg>
  );
}
function BookIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2z" />
      <path d="M19 17H6" />
    </svg>
  );
}

const SIGNUP_ERROR_MESSAGES: Record<string, string> = {
  email_address_invalid: "Enter a valid email address.",
  email_address_not_authorized:
    "This email address cannot receive a confirmation email. Contact your institution.",
  email_exists: "An account with this email already exists. Sign in instead.",
  email_provider_disabled:
    "Student registration is currently unavailable. Contact your institution.",
  over_email_send_rate_limit:
    "Too many confirmation emails were requested. Wait a few minutes and try again.",
  over_request_rate_limit:
    "Too many signup attempts were made. Wait a few minutes and try again.",
  signup_disabled:
    "Student registration is currently unavailable. Contact your institution.",
  user_already_exists: "An account with this email already exists. Sign in instead.",
  validation_failed: "Check your account details and try again.",
  weak_password: "Choose a stronger password and try again.",
};

function signupErrorMessage(error: AuthError): string {
  if (error.code && SIGNUP_ERROR_MESSAGES[error.code]) {
    return SIGNUP_ERROR_MESSAGES[error.code];
  }
  if (error.status === 429) {
    return "Too many signup attempts were made. Wait a few minutes and try again.";
  }
  if (error.status && error.status >= 500) {
    return "The account service is temporarily unavailable. Please try again shortly.";
  }
  return "Account creation failed. Check your details and try again.";
}

export default function SignupPage() {
  const router = useRouter();
  const pathname = usePathname();

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [courseId, setCourseId] = useState("");
  const [courseLevelId, setCourseLevelId] = useState("");
  const [courses, setCourses] = useState<PublicCourse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);

  const [tenantId, setTenantId] = useState("");
  const [branding, setBranding] = useState<InstitutionBranding | null>(null);
  const [destination, setDestination] = useState("/dashboard");
  const [loginHref, setLoginHref] = useState("/login");
  const [institutionSlug, setInstitutionSlug] = useState("");

  useEffect(() => {
    let active = true;
    const params = new URL(window.location.href).searchParams;
    const slug =
      institutionSlugFromPath(pathname, "/signup/") ||
      normalizeInstitutionSlug(params.get("institution"));
    setInstitutionSlug(slug);
    setDestination(safeDashboardNext(params.get("next")));
    setLoginHref(institutionLoginPath(slug));
    setBranding(null);
    setTenantId("");
    setCourses([]);
    if (!slug) {
      setError(
        "Student registration requires your institution access link. Ask your institution administrator to share it with you.",
      );
      return () => { active = false; };
    }
    setError(null);
    getInstitutionBranding(slug)
      .then((branding) => {
        if (active) {
          setBranding(branding);
          setTenantId(branding.tenant_id);
        }
      })
      .catch(() => {
        if (active) {
          setError("This institution signup link is unavailable.");
        }
    });
    return () => { active = false; };
  }, [pathname]);

  useEffect(() => {
    if (tenantId) {
      listPublicCourses(tenantId)
        .then(setCourses)
        .catch(() =>
          setError("Couldn't load courses — please refresh the page."),
        );
    }
  }, [tenantId]);

  async function handleSignup(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (!tenantId) {
      setError("Use the student registration link provided by your institution.");
      return;
    }
    if (!fullName || !email || !password) {
      setError("Please fill in your name, email and password.");
      return;
    }
    if (!courseId || !courseLevelId) {
      setError("Please select your course and level.");
      return;
    }
    setLoading(true);
    const supabase = createClient();
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          full_name: fullName,
          // The database derives the tenant from this course and always creates
          // a student. It ignores browser-supplied role/tenant metadata.
          course_id: courseId,
          course_level_id: courseLevelId,
        },
      },
    });
    setLoading(false);
    if (error) {
      // Supabase recommends branching on stable Auth error codes. Log only
      // non-sensitive diagnostics and keep arbitrary provider text out of the UI.
      console.error("Student signup failed", {
        code: error.code ?? "unknown",
        status: error.status ?? "unknown",
      });
      setError(signupErrorMessage(error));
      return;
    }
    if (data.session) {
      router.push(destination);
    } else {
      setNotice("Account created. Check your email to confirm it, then sign in.");
    }
  }

  async function handleGoogleSignup() {
    setError(null);
    setNotice(null);
    if (!tenantId) {
      setError("Use the student registration link provided by your institution.");
      return;
    }
    setGoogleLoading(true);
    try {
      // Course selection is optional here. If the student already picked one
      // from the form above we carry it through, but /auth/callback prompts
      // for it after Google sign-in when they haven't — the database
      // callback validates whichever course arrives and derives the tenant
      // before creating a student profile.
      await signInWithGoogle(
        courseId,
        courseLevelId,
        destination,
        tenantId,
        institutionSlug,
      );
    } catch {
      setError("Google sign-in could not start. Please try again.");
      setGoogleLoading(false);
    }
  }

  return (
    <div className="login-page signup-centered">
      <div className="wrap">
        <div className="right">
          <div className="card">
            <div className="card-head">
              {branding?.logo_url && (
                <div className="card-logo signup-institution-logo">
                  {/* The source is a short-lived URL from the private logo bucket. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={branding.logo_url} alt={`${branding.name} logo`} />
                </div>
              )}
              {branding?.name && (
                <p className="signup-institution-name">{branding.name}</p>
              )}
              <div className="card-title">Create your student account</div>
              <div className="card-sub">Choose your course and level to enrol</div>
            </div>

            <form className="form-body" onSubmit={handleSignup}>
              {error && <div className="err-box"><span>⚠</span><span>{error}</span></div>}
              {notice && <div className="ok-box"><span>✓</span><span>{notice}</span></div>}

              <div className="field">
                <label className="field-label" htmlFor="signup-full-name">Full name <span className="req">*</span></label>
                <div className="field-box">
                  <span className="field-icon"><UserIcon /></span>
                  <input id="signup-full-name" className="field-input" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Your full name" autoComplete="name" required />
                </div>
              </div>

              <div className="field">
                <label className="field-label" htmlFor="signup-email">Email address <span className="req">*</span></label>
                <div className="field-box">
                  <span className="field-icon"><MailIcon /></span>
                  <input id="signup-email" className="field-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@email.com" autoComplete="email" required />
                </div>
              </div>

              <div className="field">
                <label className="field-label" htmlFor="signup-password">Password <span className="req">*</span></label>
                <div className="field-box">
                  <span className="field-icon"><LockIcon /></span>
                  <input id="signup-password" className="field-input" type={showPw ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Create a password" minLength={6} autoComplete="new-password" required />
                  <button type="button" className="pw-eye" onClick={() => setShowPw((s) => !s)}>{showPw ? "Hide" : "Show"}</button>
                </div>
              </div>

              <div className="field">
                <label className="field-label" htmlFor="signup-account-type">Account type</label>
                <div className="field-box">
                  <span className="field-icon"><UserIcon /></span>
                  <input id="signup-account-type" className="field-input" value="Student" disabled />
                </div>
              </div>

              <div className="field">
                <label className="field-label" htmlFor="signup-course">Course <span className="req">*</span></label>
                <div className="field-box">
                  <span className="field-icon"><BookIcon /></span>
                  <select
                    id="signup-course"
                    className="field-input"
                    value={courseId}
                    onChange={(e) => {
                      setCourseId(e.target.value);
                      setCourseLevelId("");
                    }}
                  >
                    <option value="">Select your course…</option>
                    {courses.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="field">
                <label className="field-label" htmlFor="signup-level">Level <span className="req">*</span></label>
                <div className="field-box">
                  <span className="field-icon"><BookIcon /></span>
                  <select
                    id="signup-level"
                    className="field-input"
                    value={courseLevelId}
                    onChange={(e) => setCourseLevelId(e.target.value)}
                    disabled={!courseId}
                    required
                  >
                    <option value="">{courseId ? "Select your level…" : "Select a course first…"}</option>
                    {(courses.find((course) => course.id === courseId)?.levels ?? []).map((level) => (
                      <option key={level.id} value={level.id}>{level.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <button className="btn-signin" type="submit" disabled={loading || googleLoading || !tenantId}>
                {loading ? "Creating account…" : "Create account →"}
              </button>

              <div className="divider oauth-divider">
                <div className="div-line" />
                <div className="div-text">or</div>
                <div className="div-line" />
              </div>

              <GoogleAuthButton
                busy={googleLoading || loading || !tenantId}
                onClick={handleGoogleSignup}
              />
              <p className="oauth-help">
                Google supplies your verified name and email — you&apos;ll pick your
                course next.
              </p>
            </form>

            <div className="card-foot">
              Already have an account? <Link href={loginHref}>Sign in</Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
