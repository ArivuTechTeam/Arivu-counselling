/** Keep auth return destinations local and limited to student challenge pages. */
export function safeDashboardNext(value: string | null | undefined): string {
  if (!value) return "/dashboard";
  const path = value.split("#", 1)[0];
  return /^\/dashboard\/student\/challenge\/[A-Za-z0-9_-]+$/.test(path)
    ? path
    : "/dashboard";
}
