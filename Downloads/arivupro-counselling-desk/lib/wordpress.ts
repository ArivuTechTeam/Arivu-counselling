const WP_BASE = "https://www.arivupro.com/wp-json/wp/v2";
const CACHE_TTL_MS = 10 * 60 * 1000; // 10 min — aligned with COURSES_CACHE_TTL

type CacheEntry = { text: string; ts: number };
const cache = new Map<string, CacheEntry>();

// ── Courses API (uses ARIVUPRO_COURSES_API_URL — proven to work from Railway) ──
interface CourseRecord {
  id: number;
  title?: { rendered?: string };
  course_level?: string;
  location?: string;
  start_date?: string;
  day_timing?: string;
  exam_attempt?: string;
  fee?: string;
  status?: string;
}

let coursesCache: { data: CourseRecord[]; ts: number } | null = null;
const COURSES_CACHE_TTL = 10 * 60 * 1000; // 10 min

async function fetchCoursesAPI(): Promise<CourseRecord[]> {
  if (coursesCache && Date.now() - coursesCache.ts < COURSES_CACHE_TTL) {
    return coursesCache.data;
  }
  const base = process.env.ARIVUPRO_COURSES_API_URL;
  const key = process.env.ARIVUPRO_COURSES_API_KEY;
  if (!base || !key) return [];
  try {
    // Append per_page as a raw string — do NOT use new URL() / searchParams
    // because it percent-encodes commas in the _fields param (id%2Ctitle...)
    // which breaks WordPress field filtering.
    const separator = base.includes('?') ? '&' : '?';
    const fetchUrl = `${base}${separator}per_page=100`;
    const fetchPromise = fetch(fetchUrl, {
      headers: {
        'Accept': 'application/json,text/html,*/*',
        'X-API-KEY': key,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://www.arivupro.com/',
        'Origin': 'https://www.arivupro.com',
        'Cache-Control': 'no-cache',
      },
      cache: 'no-store',
    });
    const res = await Promise.race([
      fetchPromise,
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error('timeout')), 8000)),
    ]);
    if (!res.ok) return [];
    const data = await res.json() as CourseRecord[];
    if (!Array.isArray(data)) return [];
    coursesCache = { data, ts: Date.now() };
    return data;
  } catch {
    return [];
  }
}

function formatCoursesForBot(courses: CourseRecord[], query: string): string {
  if (!courses.length) return '';
  const q = query.toLowerCase();

  // Filter by course type if detectable from query
  // Order matters: more specific matches first (CMA USA before CMA, CA Foundation before CA)
  const filtered = courses.filter(c => {
    const level = (c.course_level || '').toLowerCase();
    const title = (c.title?.rendered || '').toLowerCase();
    const combined = level + ' ' + title;

    if (q.includes('cma usa') || q.includes('cma-usa')) return combined.includes('cma usa') || combined.includes('cma-usa');
    if (q.includes('cma india') || q.includes('cma')) return (combined.includes('cma') && !combined.includes('cma usa') && !combined.includes('cma-usa'));
    if (q.includes('acca')) return combined.includes('acca');
    if (q.includes('cfa')) return combined.includes('cfa');
    if (q.includes('frm')) return combined.includes('frm');
    if (q.includes('cs ') || q.includes(' cs') || q === 'cs') return combined.includes(' cs') || level.startsWith('cs');

    // CA level filters — check course is CA first
    const isCA = combined.includes('ca ') || combined.includes(' ca') || level.startsWith('ca');
    if (q.includes('ca foundation') || (q.includes('foundation') && isCA)) return combined.includes('foundation') && isCA;
    if (q.includes('ca inter') || (q.includes('inter') && isCA)) return combined.includes('inter') && isCA;
    if (q.includes('ca final') || (q.includes('final') && isCA)) return combined.includes('final') && isCA;
    if (q.includes('ca ') || q.startsWith('ca')) return isCA;

    // Generic level words without course context — match any course with that level
    if (q.includes('foundation')) return combined.includes('foundation');
    if (q.includes('inter')) return combined.includes('inter');
    if (q.includes('final')) return combined.includes('final');

    return true; // no filter — return all
  });

  // Location filter — if student mentioned a city, prefer matching location
  const CITY_ALIASES: Record<string, string[]> = {
    chennai: ['chennai', 'madras'],
    bangalore: ['bangalore', 'bengaluru'],
    hyderabad: ['hyderabad', 'hyd'],
    online: ['online', 'live online', 'virtual'],
  };
  let locationFiltered = filtered.length > 0 ? filtered : courses;
  for (const [_city, aliases] of Object.entries(CITY_ALIASES)) {
    if (aliases.some(a => q.includes(a))) {
      const byCity = locationFiltered.filter(c =>
        aliases.some(a => (c.location || '').toLowerCase().includes(a))
      );
      if (byCity.length > 0) { locationFiltered = byCity; break; }
      // city not in data, keep full list (don't return empty)
      break;
    }
  }

  const todayMs = Date.now();

  // Parse any date format WP might return: "2026-11-14", "14 November 2026", "November 14, 2026" etc.
  function parseDateMs(raw: string | undefined): number {
    if (!raw) return Infinity; // no date = treat as future (don't hide it)
    const d = new Date(raw);
    if (!isNaN(d.getTime())) return d.getTime();
    // Try manual parse for "14 November 2026" style
    const m = raw.match(/(\d{1,2})\s+(\w+)\s+(\d{4})/);
    if (m) {
      const d2 = new Date(`${m[2]} ${m[1]}, ${m[3]}`);
      if (!isNaN(d2.getTime())) return d2.getTime();
    }
    return Infinity; // unparseable = treat as future
  }

  const pool = locationFiltered;

  // Sort by date ascending
  const sorted = [...pool].sort((a, b) => parseDateMs(a.start_date) - parseDateMs(b.start_date));

  const upcoming = sorted.filter(c => parseDateMs(c.start_date) >= todayMs);
  const past = sorted.filter(c => c.start_date && parseDateMs(c.start_date) < todayMs);

  const formatLine = (c: CourseRecord, note?: string) => {
    const title = stripHtml(c.title?.rendered || '');
    const parts = [
      c.start_date ? `Start: ${c.start_date}` : '',
      c.day_timing ? `Timing: ${c.day_timing}` : '',
      c.location ? `Location: ${c.location}` : '',
      c.exam_attempt ? `Exam: ${c.exam_attempt}` : '',
      c.fee ? `Fee: ${c.fee}` : '',
    ].filter(Boolean).join(' | ');
    return `• ${title}${parts ? ' — ' + parts : ''}${note ? ' [' + note + ']' : ''}`;
  };

  if (upcoming.length > 0) {
    return `UPCOMING BATCHES FROM ARIVUPRO:\n${upcoming.slice(0, 15).map(c => formatLine(c)).join('\n')}`;
  }

  if (past.length > 0) {
    return `NOTE: No upcoming batches in our system right now. These batches have already started or ended — tell the student and ask them to contact ArivuPro or visit arivupro.com for the next confirmed batch date.\nPAST BATCHES (already started/ended):\n${past.slice(0, 10).map(c => formatLine(c, 'ENDED')).join('\n')}`;
  }

  return '';
}

// Course slug map — used to fetch specific course pages directly
const COURSE_SLUGS: Record<string, string[]> = {
  CA: ["ca-foundation", "ca-inter", "ca-final", "ca-course-in-india", "offline-courses-demo"],
  CMA: ["cma-india", "cma-foundation", "cma-inter", "cma-final"],
  ACCA: ["acca"],
  CFA: ["cfa"],
  FRM: ["frm"],
  CPA: ["cpa"],
  CS: ["cs"],
};

// Keywords that tell us a student is asking about batch/schedule/fee
const BATCH_KEYWORDS = /batch|next.?batch|start|schedule|fee|fees|cost|price|upcoming|join|enroll|admission|date|timing|when|serthuk|join.?pann|evlo|sollu|class.*start|aaagum|serunga|register/i;

function stripHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

// Extract only the text that likely contains batch/fee info (look for short paragraphs)
function extractBatchInfo(html: string): string {
  const stripped = stripHtml(html);
  // Find sentences mentioning batch, fee, date, November, etc.
  const sentences = stripped.split(/(?<=[.!?])\s+/);
  const relevant = sentences.filter(s =>
    /batch|fee|fees|nov|oct|jan|feb|mar|apr|may|jun|jul|aug|sep|₹|rs\.|rupee|lakh|enroll|start|upcoming|next|date|timing|\d{1,2}\s*(nov|oct|jan|feb)/i.test(s)
  );
  const summary = relevant.length > 0
    ? relevant.slice(0, 8).join(" ")
    : stripped.slice(0, 800);
  return summary.slice(0, 1200);
}

function truncate(text: string, max = 2000): string {
  return text.length > max ? text.slice(0, max) + "…" : text;
}

async function fetchPageBySlug(slug: string): Promise<string> {
  try {
    const res = await Promise.race([
      fetch(`${WP_BASE}/pages?slug=${slug}&_fields=title,content`),
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error('timeout')), 5000)),
    ]);
    if (!res.ok) return "";
    const pages = await res.json() as Array<{ title: { rendered: string }; content: { rendered: string } }>;
    if (!pages.length) return "";
    const title = stripHtml(pages[0].title?.rendered || "");
    const body = extractBatchInfo(pages[0].content?.rendered || "");
    return body ? `[${title}]: ${body}` : "";
  } catch {
    return "";
  }
}

export async function fetchWordPressContext(query: string, course?: string): Promise<string> {
  const cacheKey = `${course || ""}|${query.toLowerCase().slice(0, 80)}`;
  const cached = cache.get(cacheKey);
  if (cached && Date.now() - cached.ts < CACHE_TTL_MS) return cached.text;

  const hasTamil = /[஀-௿]/.test(query);
  const isBatchQuery = BATCH_KEYWORDS.test(query) || hasTamil;
  const results: string[] = [];

  // ── Primary: use the live Courses API (works from Railway, auto-updates) ──
  if (isBatchQuery) {
    try {
      const courses = await fetchCoursesAPI();
      if (courses.length > 0) {
        const formatted = formatCoursesForBot(courses, `${course || ''} ${query}`);
        if (formatted) results.push(formatted);
      }
    } catch { /* non-fatal */ }
  }

  // WP REST fallback removed — Cloudflare blocks it from Railway (403) and it
  // hangs for 30-120s on unreliable connections. The Courses API above covers
  // all batch/fee data. Non-batch queries don't need WP content.

  const text = truncate(results.join("\n\n"));
  cache.set(cacheKey, { text, ts: Date.now() });
  return text;
}
