// Fetches live content from arivupro.com WordPress REST API
// Used to give Gemini real batch/fee/schedule context instead of saying "verify with team"

const WP_BASE = process.env.WORDPRESS_BASE_URL || "https://arivupro.com/wp-json/wp/v2";
const CACHE_TTL_MS = 30 * 60 * 1000; // 30 minutes

type CacheEntry = { text: string; ts: number };
const cache = new Map<string, CacheEntry>();

function stripHtml(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

function truncate(text: string, maxChars = 1500): string {
  return text.length > maxChars ? text.slice(0, maxChars) + "…" : text;
}

export async function fetchWordPressContext(query: string): Promise<string> {
  const cacheKey = query.toLowerCase().slice(0, 80);
  const cached = cache.get(cacheKey);
  if (cached && Date.now() - cached.ts < CACHE_TTL_MS) return cached.text;

  const results: string[] = [];

  try {
    // Search posts and pages for query-relevant content
    const [searchRes, pagesRes] = await Promise.allSettled([
      fetch(`${WP_BASE}/search?search=${encodeURIComponent(query)}&type=post&per_page=3&_fields=title,url`, { signal: AbortSignal.timeout(4000) }),
      fetch(`${WP_BASE}/pages?search=${encodeURIComponent(query)}&per_page=3&_fields=title,content,link`, { signal: AbortSignal.timeout(4000) }),
    ]);

    // Extract from pages (richer content)
    if (pagesRes.status === "fulfilled" && pagesRes.value.ok) {
      const pages = await pagesRes.value.json() as Array<{ title: { rendered: string }; content: { rendered: string }; link: string }>;
      for (const page of pages) {
        const title = stripHtml(page.title?.rendered || "");
        const body = stripHtml(page.content?.rendered || "").slice(0, 600);
        if (body) results.push(`[${title}]: ${body}`);
      }
    }

    // Extract from search (post titles + links as signals)
    if (searchRes.status === "fulfilled" && searchRes.value.ok) {
      const posts = await searchRes.value.json() as Array<{ title: string; url: string }>;
      for (const post of posts) {
        const title = typeof post.title === "string" ? post.title : stripHtml((post.title as { rendered?: string })?.rendered || "");
        if (title) results.push(`[Post found]: ${title}`);
      }
    }
  } catch {
    // WordPress unreachable — return empty, Gemini answers without context
    return "";
  }

  const text = truncate(results.join("\n\n"));
  cache.set(cacheKey, { text, ts: Date.now() });
  return text;
}
