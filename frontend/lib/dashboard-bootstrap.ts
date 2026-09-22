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

type DashboardBootstrap = {
  version: 1;
  userId: string;
  role: DashboardRole;
  mustChangePassword: boolean;
};

const STORAGE_KEY = "dashboard-bootstrap-v1";

export function isDashboardRole(value: unknown): value is DashboardRole {
  return (
    typeof value === "string" &&
    (DASHBOARD_ROLES as readonly string[]).includes(value)
  );
}

export function readDashboardBootstrap(
  userId: string,
): DashboardBootstrap | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DashboardBootstrap>;
    if (
      parsed.version !== 1 ||
      parsed.userId !== userId ||
      !isDashboardRole(parsed.role) ||
      typeof parsed.mustChangePassword !== "boolean"
    ) {
      window.sessionStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed as DashboardBootstrap;
  } catch {
    return null;
  }
}

export function writeDashboardBootstrap(
  userId: string,
  role: DashboardRole,
  mustChangePassword: boolean,
): void {
  try {
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        version: 1,
        userId,
        role,
        mustChangePassword,
      } satisfies DashboardBootstrap),
    );
  } catch {
    // A blocked sessionStorage only removes the fast path; auth still works.
  }
}

export function clearDashboardBootstrap(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Signing out must not depend on browser storage being available.
  }
}

export function dashboardDestination(
  role: DashboardRole,
  requestedPath: string,
): string {
  return requestedPath === "/dashboard" ? HOME_BY_ROLE[role] : requestedPath;
}
