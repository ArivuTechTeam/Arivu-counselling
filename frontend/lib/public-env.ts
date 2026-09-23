function required(name: string, value: string | undefined): string {
  const normalized = value?.trim();
  if (
    !normalized ||
    /^(replace_with_|your-|your_)/i.test(normalized)
  ) {
    throw new Error(`Missing required public environment variable: ${name}`);
  }
  return normalized;
}

function absoluteUrl(name: string, value: string | undefined): string {
  const normalized = required(name, value);
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error(`${name} must be an absolute URL.`);
  }
  const local = ["localhost", "127.0.0.1"].includes(parsed.hostname);
  if (parsed.protocol !== "https:" && !(local && parsed.protocol === "http:")) {
    throw new Error(`${name} must use HTTPS outside localhost development.`);
  }
  return normalized.replace(/\/$/, "");
}

export const PUBLIC_ENV = Object.freeze({
  supabaseUrl: absoluteUrl(
    "NEXT_PUBLIC_SUPABASE_URL",
    process.env.NEXT_PUBLIC_SUPABASE_URL,
  ),
  supabaseAnonKey: required(
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  ),
  apiBaseUrl: absoluteUrl(
    "NEXT_PUBLIC_API_BASE_URL",
    process.env.NEXT_PUBLIC_API_BASE_URL,
  ),
});
