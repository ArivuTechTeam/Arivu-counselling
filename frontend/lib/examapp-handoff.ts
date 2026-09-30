/** UI visibility mirrors the backend's explicit super-admin exemption. */
export function isExamAppHandoffVisible(
  role: string | null,
  tenantEnabled: boolean,
): boolean {
  return role === "super_admin" || tenantEnabled;
}
