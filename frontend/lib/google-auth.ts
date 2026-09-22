import { createClient } from "@/lib/supabase";

export const PENDING_GOOGLE_COURSE_KEY = "pending_google_course_id";
export const PENDING_GOOGLE_LEVEL_KEY = "pending_google_course_level_id";
export const PENDING_AUTH_NEXT_KEY = "pending_auth_next";
export const PENDING_GOOGLE_TENANT_KEY = "pending_google_tenant_id";

export async function signInWithGoogle(
  courseId?: string,
  courseLevelId?: string,
  nextPath?: string,
  tenantId?: string,
): Promise<void> {
  if (courseId) {
    window.sessionStorage.setItem(PENDING_GOOGLE_COURSE_KEY, courseId);
  } else {
    window.sessionStorage.removeItem(PENDING_GOOGLE_COURSE_KEY);
  }
  if (courseLevelId) {
    window.sessionStorage.setItem(PENDING_GOOGLE_LEVEL_KEY, courseLevelId);
  } else {
    window.sessionStorage.removeItem(PENDING_GOOGLE_LEVEL_KEY);
  }
  if (tenantId) {
    window.sessionStorage.setItem(PENDING_GOOGLE_TENANT_KEY, tenantId);
  } else {
    window.sessionStorage.removeItem(PENDING_GOOGLE_TENANT_KEY);
  }
  if (nextPath && nextPath !== "/dashboard") {
    window.sessionStorage.setItem(PENDING_AUTH_NEXT_KEY, nextPath);
  } else {
    window.sessionStorage.removeItem(PENDING_AUTH_NEXT_KEY);
  }

  const redirectTo = new URL("/auth/callback", window.location.origin).toString();
  const { error } = await createClient().auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo },
  });

  if (error) throw error;
}
