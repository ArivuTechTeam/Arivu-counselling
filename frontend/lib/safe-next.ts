/** Keep auth return destinations local and limited to protected dashboard pages. */
export function safeDashboardNext(value: string | null | undefined): string {
  if (!value) return "/dashboard";
  const candidate = value.trim();
  if (
    !candidate.startsWith("/dashboard") ||
    candidate.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return "/dashboard";
  }
  try {
    const base = "https://quiz-platform.invalid";
    const parsed = new URL(candidate, base);
    if (
      parsed.origin !== base ||
      (parsed.pathname !== "/dashboard" &&
        !parsed.pathname.startsWith("/dashboard/"))
    ) {
      return "/dashboard";
    }
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return "/dashboard";
  }
}
