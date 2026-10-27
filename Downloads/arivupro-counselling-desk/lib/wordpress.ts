// Retrieves current public ArivuPro content. The WordPress REST API is protected
// on the production site, so normal public HTML pages are used as the fallback.

const SITE_BASE = (process.env.ARIVUPRO_SITE_URL || "https://www.arivupro.com").replace(/\/$/, "");
const COURSES_API_URL = process.env.ARIVUPRO_COURSES_API_URL || `${SITE_BASE}/wp-json/wp/v2/courses`;
const COURSES_API_KEY = process.env.ARIVUPRO_COURSES_API_KEY;
const CACHE_TTL_MS = 2 * 60 * 1000;

type CacheEntry = { text: string; ts: number };
const cache = new Map<string, CacheEntry>();

function stripHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<noscript[\s\S]*?<\/noscript>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

async function fetchPublicPage(path: string): Promise<string> {
  const response = await fetch(`${SITE_BASE}${path}`, {
    headers: { "User-Agent": "Mozilla/5.0 ArivuPro-Counselling/1.0", Accept: "text/html" },
    cache: "no-store",
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) return "";
  return stripHtml(await response.text());
}

async function fetchCoursesApi(): Promise<string> {
  if (!COURSES_API_KEY) return "";
  const apiUrl = new URL(COURSES_API_URL);
  apiUrl.searchParams.set("per_page", "100");
  const response = await fetch(apiUrl, {
    headers: { Accept: "application/json", "X-API-KEY": COURSES_API_KEY },
    cache: "no-store",
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) return "";
  const payload = await response.json() as unknown;
  return JSON.stringify(payload);
}

function truncate(text: string, maxChars = 1500): string {
  return text.length > maxChars ? text.slice(0, maxChars) + "…" : text;
}

export async function fetchWordPressContext(query: string, course?: string, level?: string): Promise<string> {
  const cacheKey = `${course || ""}|${level || ""}|${query.toLowerCase().slice(0, 80)}`;
  const cached = cache.get(cacheKey);
  if (cached && Date.now() - cached.ts < CACHE_TTL_MS) return cached.text;

  const results: string[] = [];

  try {
    // Prefer the authenticated WordPress course API; public pages remain a fallback.
    const pages = await Promise.allSettled([fetchCoursesApi(), fetchPublicPage("/"), fetchPublicPage("/shop")]);
    const terms = `${course || ""} ${level || ""} ${query}`.toLowerCase().split(/[^a-z0-9]+/).filter(w => w.length > 2).slice(0, 10);
    for (const page of pages) {
      if (page.status === "fulfilled" && page.value && terms.some(term => page.value.toLowerCase().includes(term))) {
        results.push(page.value);
      }
    }

  } catch {
    // WordPress unreachable — return empty, Gemini answers without context
    return "";
  }

  const text = truncate(results.join("\n\n"), 9000);
  cache.set(cacheKey, { text, ts: Date.now() });
  return text;
}
