import { createClient } from "@/lib/supabase";

export const PENDING_GOOGLE_COURSE_KEY = "pending_google_course_id";
export const PENDING_AUTH_NEXT_KEY = "pending_auth_next";

export async function signInWithGoogle(
  courseId?: string,
  nextPath?: string,
): Promise<void> {
  if (courseId) {
    window.sessionStorage.setItem(PENDING_GOOGLE_COURSE_KEY, courseId);
  } else {
    window.sessionStorage.removeItem(PENDING_GOOGLE_COURSE_KEY);
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
