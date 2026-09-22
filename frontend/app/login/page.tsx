"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { GoogleAuthButton } from "@/components/auth/google-auth-button";
import { getInstitutionBranding, InstitutionBranding, warmBackend } from "@/lib/api";
import {
  dashboardDestination,
  isDashboardRole,
  writeDashboardBootstrap,
} from "@/lib/dashboard-bootstrap";
import { signInWithGoogle } from "@/lib/google-auth";
import { safeDashboardNext } from "@/lib/safe-next";
import { createClient } from "@/lib/supabase";
import "./login.css";

function MailIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12h14" />
      <path d="m13 6 6 6-6 6" />
    </svg>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const pathname = usePathname();
  const institutionSlug = pathname.startsWith("/login/")
    ? decodeURIComponent(pathname.slice("/login/".length).split("/")[0] ?? "")
    : "";
  const pageRef = useRef<HTMLDivElement>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [branding, setBranding] = useState<InstitutionBranding | null>(null);
  const [brandingError, setBrandingError] = useState<string | null>(null);
  const [signupHref, setSignupHref] = useState("/signup");

  function requestedDestination() {
    return safeDashboardNext(
      new URL(window.location.href).searchParams.get("next"),
    );
  }

  async function handleSignIn(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!email || !password) {
      setError("Please enter your email and password.");
      return;
    }

    setLoading(true);
    const supabase = createClient();
    const { data: signInData, error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (signInError) {
      setLoading(false);
      setError("Sign-in failed. Check your credentials and try again.");
      return;
    }
    const user = signInData.user;
    if (!user) {
      setLoading(false);
      setError("Sign-in did not create a session. Please try again.");
      return;
    }
    warmBackend();
    const { data: profile, error: profileError } = await supabase
      .from("profiles")
      .select("role,must_change_password")
      .eq("id", user.id)
      .single();
    setLoading(false);
    if (profileError || !isDashboardRole(profile?.role)) {
      await supabase.auth.signOut({ scope: "local" });
      setError(
        "Your account profile could not be loaded. Please contact your administrator.",
      );
      return;
    }
    writeDashboardBootstrap(
      user.id,
      profile.role,
      Boolean(profile.must_change_password),
    );
    router.push(dashboardDestination(profile.role, requestedDestination()));
  }

  async function handleGoogleSignIn() {
    setError(null);
    setNotice(null);
    setGoogleLoading(true);
    try {
      if (institutionSlug && !branding) {
        throw new Error("Institution branding is not ready.");
      }
      // Existing users do not need a course. New Google users choose one on
      // the callback page before the profile is created.
      await signInWithGoogle(
        undefined,
        undefined,
        requestedDestination(),
        branding?.tenant_id,
      );
    } catch {
      setError("Google sign-in could not start. Please try again.");
      setGoogleLoading(false);
    }
  }

  useEffect(() => {
    const url = new URL(window.location.href);
    const signupParams = new URLSearchParams();
    if (institutionSlug) signupParams.set("institution", institutionSlug);
    const signupNext = safeDashboardNext(url.searchParams.get("next"));
    if (signupNext !== "/dashboard") signupParams.set("next", signupNext);
    setSignupHref(
      `/signup${signupParams.size ? `?${signupParams.toString()}` : ""}`,
    );
    const reason = url.searchParams.get("reason");
    if (reason === "session-expired") {
      setNotice("Your session expired. Please log in again.");
    } else if (reason === "password-changed") {
      setNotice("Your password has been changed. Please sign in with your new password.");
    } else if (reason === "account-deleted") {
      setNotice("Your account and personal activity have been deleted.");
    } else if (reason === "profile-unavailable") {
      setNotice(
        "Your account is not fully set up. Please contact your administrator.",
      );
    }
    if (reason) {
      url.searchParams.delete("reason");
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    }
  }, [institutionSlug]);

  useEffect(() => {
    let active = true;
    // Wake a sleeping API while the user is reading or completing the form so
    // the first authenticated dashboard request does not pay the full cold start.
    warmBackend();
    // This is only a convenience redirect for an already-signed-in browser
    // tab. Restore the local session instead of blocking on the Auth server;
    // dashboard data and role access are still verified downstream.
    createClient().auth.getSession().then(({ data: { session } }) => {
      if (active && session?.user) router.replace(requestedDestination());
    });
    return () => { active = false; };
    // The intended destination is read from the current URL once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let active = true;
    setBranding(null);
    setBrandingError(null);
    if (!institutionSlug) return () => { active = false; };
    getInstitutionBranding(institutionSlug)
      .then((result) => {
        if (active) setBranding(result);
      })
      .catch(() => {
        if (active) {
          setBrandingError(
            "This institution login link is unavailable. You can still sign in below.",
          );
        }
      });
    return () => { active = false; };
  }, [institutionSlug]);

  // Match the mobile layout to the visible viewport when the software
  // keyboard opens. This keeps the primary action reachable on iOS/Android.
  useEffect(() => {
    const viewport = window.visualViewport;
    const updateViewport = () => {
      const page = pageRef.current;
      if (!page) return;
      page.style.setProperty(
        "--login-viewport-height",
        `${viewport?.height ?? window.innerHeight}px`,
      );
      page.style.setProperty(
        "--login-viewport-offset",
        `${viewport?.offsetTop ?? 0}px`,
      );
    };
    updateViewport();
    viewport?.addEventListener("resize", updateViewport);
    viewport?.addEventListener("scroll", updateViewport);
    window.addEventListener("resize", updateViewport);
    return () => {
      viewport?.removeEventListener("resize", updateViewport);
      viewport?.removeEventListener("scroll", updateViewport);
      window.removeEventListener("resize", updateViewport);
    };
  }, []);

  function keepMobileActionsVisible(event: React.FocusEvent<HTMLInputElement>) {
    window.setTimeout(() => {
      const scroller = event.currentTarget.closest<HTMLElement>(".login-auth-scroll");
      const signIn = scroller?.querySelector<HTMLElement>(".login-primary");
      if (!scroller || !signIn || window.innerWidth > 760) return;

      const viewportBottom = window.visualViewport
        ? window.visualViewport.offsetTop + window.visualViewport.height
        : window.innerHeight;
      const actionBottom = signIn.getBoundingClientRect().bottom;
      if (actionBottom > viewportBottom - 16) {
        scroller.scrollBy({
          top: actionBottom - viewportBottom + 24,
          behavior: "smooth",
        });
      }
    }, 180);
  }

  return (
    <div className="login-page login-redesign" ref={pageRef}>
      <main className="login-layout">
        <section className="login-auth" aria-labelledby="login-title">
          <div className="login-auth-scroll">
            <div className="login-auth-card">
              {branding?.logo_url && (
                <div className="login-institution-logo">
                  {/* The source is a short-lived URL from the private logo bucket. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={branding.logo_url} alt={`${branding.name} logo`} />
                </div>
              )}

              <header className="login-auth-header">
                <p className="login-auth-kicker">
                  {branding?.name ?? "Quiz platform"}
                </p>
                <h2 id="login-title">Welcome back</h2>
                <p>Sign in to continue to your dashboard.</p>
              </header>

              <form className="login-form" onSubmit={handleSignIn}>
                {notice && (
                  <div className="login-message login-message-info" role="status">
                    <span aria-hidden="true">i</span>
                    <p>{notice}</p>
                  </div>
                )}
                {error && (
                  <div className="login-message login-message-error" role="alert">
                    <span aria-hidden="true">!</span>
                    <p>{error}</p>
                  </div>
                )}
                {brandingError && (
                  <div className="login-message login-message-info" role="status">
                    <span aria-hidden="true">i</span>
                    <p>{brandingError}</p>
                  </div>
                )}

                <div className="login-control">
                  <label htmlFor="login-email">Email address</label>
                  <div className="login-input-wrap">
                    <span className="login-input-icon"><MailIcon /></span>
                    <input
                      id="login-email"
                      type="email"
                      name="email"
                      inputMode="email"
                      autoComplete="email"
                      autoCapitalize="none"
                      autoCorrect="off"
                      enterKeyHint="next"
                      placeholder="you@email.com"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      onFocus={keepMobileActionsVisible}
                      required
                    />
                  </div>
                </div>

                <div className="login-control">
                  <label htmlFor="login-password">Password</label>
                  <div className="login-input-wrap">
                    <span className="login-input-icon"><LockIcon /></span>
                    <input
                      id="login-password"
                      type={showPw ? "text" : "password"}
                      name="password"
                      autoComplete="current-password"
                      enterKeyHint="go"
                      placeholder="Enter your password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      onFocus={keepMobileActionsVisible}
                      required
                    />
                    <button
                      type="button"
                      className="login-password-toggle"
                      aria-label={showPw ? "Hide password" : "Show password"}
                      aria-pressed={showPw}
                      onClick={() => setShowPw((visible) => !visible)}
                    >
                      {showPw ? "Hide" : "Show"}
                    </button>
                  </div>
                </div>

                <p className="login-password-help">
                  Forgot your password? Contact your institution administrator.
                </p>

                <button
                  className="login-primary"
                  type="submit"
                  disabled={loading || googleLoading}
                >
                  <span>{loading ? "Signing in…" : "Sign in"}</span>
                  {!loading && <ArrowIcon />}
                </button>

                <div className="login-divider" aria-hidden="true">
                  <span />
                  <p>or continue with</p>
                  <span />
                </div>

                <GoogleAuthButton
                  busy={
                    googleLoading ||
                    loading ||
                    Boolean(institutionSlug && !branding)
                  }
                  onClick={handleGoogleSignIn}
                />
              </form>

              <div className="login-register">
                <p>New here?</p>
                <Link href={signupHref}>Create a student account <ArrowIcon /></Link>
              </div>

              <p className="login-legal">
                By signing in, you agree to our <Link href="/terms">Terms of Service</Link>
                {" and "}<Link href="/privacy">Privacy Policy</Link>.
              </p>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
