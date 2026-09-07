import { createClient } from "@/lib/supabase";

export const PENDING_GOOGLE_COURSE_KEY = "pending_google_course_id";

export async function signInWithGoogle(courseId?: string): Promise<void> {
  if (courseId) {
    window.sessionStorage.setItem(PENDING_GOOGLE_COURSE_KEY, courseId);
  } else {
    window.sessionStorage.removeItem(PENDING_GOOGLE_COURSE_KEY);
  }

  const redirectTo = new URL("/auth/callback", window.location.origin).toString();
  const { error } = await createClient().auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo },
  });

  if (error) throw error;
}
