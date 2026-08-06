import { redirect } from "next/navigation";

/**
 * The site root. There is no marketing page in Phase 1, so we send visitors
 * straight to the dashboard router, which itself bounces to /login if the
 * user isn't authenticated.
 */
export default function Home() {
  redirect("/dashboard");
}
