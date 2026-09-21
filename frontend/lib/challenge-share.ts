export function formatChallengeCode(code: string | null | undefined): string {
  if (!code) return "";
  const compact = code.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  return compact.length === 8
    ? `${compact.slice(0, 4)}-${compact.slice(4)}`
    : compact;
}

export function challengeInviteUrl(
  origin: string,
  token: string,
  institutionSlug: string | null | undefined,
): string {
  const destination = `/dashboard/student/challenge/${encodeURIComponent(token)}`;
  if (!institutionSlug) return `${origin}${destination}`;
  return `${origin}/login/${encodeURIComponent(institutionSlug)}?next=${encodeURIComponent(destination)}`;
}
