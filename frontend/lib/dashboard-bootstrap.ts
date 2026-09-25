export const DASHBOARD_ROLES = [
  "super_admin",
  "institution_admin",
  "teacher",
  "student",
] as const;

export type DashboardRole = (typeof DASHBOARD_ROLES)[number];

export const HOME_BY_ROLE: Record<DashboardRole, string> = {
  super_admin: "/dashboard/super-admin",
  institution_admin: "/dashboard/institution-admin",
  teacher: "/dashboard/teacher",
  student: "/dashboard/student",
};

// Remove the legacy role cache on sign-out. Role-specific pages now wait for
// the backend profile instead of trusting a saved browser value.
const STORAGE_KEY = "dashboard-bootstrap-v1";

export function isDashboardRole(value: unknown): value is DashboardRole {
  return (
    typeof value === "string" &&
    (DASHBOARD_ROLES as readonly string[]).includes(value)
  );
}

export function clearDashboardBootstrap(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Signing out must not depend on browser storage being available.
  }
}

export function dashboardContentState(
  profileVerified: boolean,
  bootstrapError: string | null,
  pathValid: boolean,
  pathname: string,
): "error" | "content" | "loading" {
  if (!profileVerified && bootstrapError) return "error";
  if (profileVerified && pathValid && pathname !== "/dashboard") return "content";
  return "loading";
}

export function dashboardDestination(
  role: DashboardRole,
  requestedPath: string,
): string {
  return requestedPath === "/dashboard" ? HOME_BY_ROLE[role] : requestedPath;
}
