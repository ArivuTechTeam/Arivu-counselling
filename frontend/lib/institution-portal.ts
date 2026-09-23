const INSTITUTION_SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function normalizeInstitutionSlug(value: string | null | undefined): string {
  const slug = (value ?? "").trim().toLowerCase();
  return INSTITUTION_SLUG.test(slug) ? slug : "";
}

export function institutionLoginPath(subdomain: string): string {
  const slug = normalizeInstitutionSlug(subdomain);
  return slug ? `/login/${encodeURIComponent(slug)}` : "/login";
}

export function institutionSignupPath(
  subdomain: string,
  nextPath?: string,
): string {
  const slug = normalizeInstitutionSlug(subdomain);
  if (!slug) return "/signup";
  const path = `/signup/${encodeURIComponent(slug)}`;
  return nextPath && nextPath !== "/dashboard"
    ? `${path}?next=${encodeURIComponent(nextPath)}`
    : path;
}

export function institutionLoginUrl(subdomain: string, origin: string): string {
  return new URL(institutionLoginPath(subdomain), origin).toString();
}

export function institutionSlugFromPath(
  pathname: string,
  prefix: "/login/" | "/signup/",
): string {
  if (!pathname.startsWith(prefix)) return "";
  const encoded = pathname.slice(prefix.length).split("/")[0] ?? "";
  try {
    return normalizeInstitutionSlug(decodeURIComponent(encoded));
  } catch {
    return "";
  }
}
