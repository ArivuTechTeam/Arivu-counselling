import { talkingPoints } from "@/lib/counselling-answers";
import { scriptIndex, lookupWpData } from "@/lib/bot-knowledge";
import { extractSlots, mergeSlots } from "@/lib/slot-filler";
import { fetchWordPressContext } from "@/lib/wordpress";
import {
  calculateEscalationScore,
  detectExplicitEscalation,
  parseSentimentScore,
  ESCALATION_THRESHOLD,
} from "@/lib/escalation";

// ArivuPro base knowledge — always injected so Gemini knows who we are
const ARIVUPRO_BASE = `ArivuPro Academy is a professional coaching institute based in Chennai, India.
Courses offered: CA Foundation, CA Inter, CA Final, CMA India (Foundation/Inter/Final), CMA USA (Part 1 & Part 2), ACCA, CFA (Level 1/2/3), FRM (Part 1 & 2), CPA, CS (Foundation/Executive/Professional).
Teaching modes: Classroom (Chennai), Live Online, Recorded.
Contact: marketing@arivupro.com | Website: arivupro.com
Sessions: Mon-Sat, 9 AM - 7 PM IST. Free 30-min counselling available.
Batches: New batches start regularly — always verify latest dates with team.

GOVERNING BOARDS & EXAM BODIES:
- CA (Chartered Accountant): Conducted by ICAI — Institute of Chartered Accountants of India. Levels: Foundation → Inter → Final. India's premier accounting qualification.
- CMA India (Cost & Management Accountant): Conducted by ICMAI — Institute of Cost Accountants of India (formerly ICWAI). Levels: Foundation → Inter → Final.
- CMA USA: Conducted by IMA — Institute of Management Accountants (USA). Two parts: Part 1 (Financial Planning & Analytics) and Part 2 (Strategic Financial Management). Global qualification.
- CS (Company Secretary): Conducted by ICSI — Institute of Company Secretaries of India. Levels: Foundation → Executive → Professional.
- ACCA (Association of Chartered Certified Accountants): UK-based global body. Applied Knowledge → Applied Skills → Strategic Professional levels.
- CFA (Chartered Financial Analyst): Conducted by CFA Institute (USA). Three levels: Level 1, 2, 3. Global investment/finance qualification.
- FRM (Financial Risk Manager): Conducted by GARP — Global Association of Risk Professionals (USA). Two parts: FRM Part 1 and Part 2.
- CPA (Certified Public Accountant): Conducted by AICPA — American Institute of CPAs (USA). Four sections: AUD, BEC, FAR, REG.`;

export const dynamic = "force-dynamic";

// ─── Types ────────────────────────────────────────────────────────────────────

interface CollectedData {
  name?: string;
  phone?: string;
  email?: string;
  course?: string;
}

interface SessionMeta {
  turnCount: number;
  noMatchCount: number;
  repeatCount: number;
  cumulativeEscalationScore: number;
}

interface BotRequestBody {
  sessionId: string;
  message?: string;
  audioBase64?: string;
  isVoice?: boolean;
  history: Array<{ role: "student" | "bot"; content: string }>;
  collectedData: CollectedData;
  sessionMeta: SessionMeta;
}

type BotAction =
  | "answer"
  | "collect_name"
  | "collect_phone"
  | "collect_email"
  | "show_calendly"
  | "confirmed";

interface BotResponse {
  reply: string;
  action: BotAction;
  escalationScore: number;
  cumulativeScore: number;
  collectedData: CollectedData;
  sessionMeta: SessionMeta;
  language: string;
  source: "curated" | "gemini" | "wp";
  calendlyUrl?: string;
  replyAudio?: string | null;
}

// ─── System prompt (student-facing, conversational) ───────────────────────────

const BOT_SYSTEM = `You are Arivu, a friendly AI counsellor at ArivuPro Academy. You talk directly to students.

LANGUAGE RULE — CRITICAL:
- Default language is ENGLISH. Reply in English unless the student is clearly writing in another language.
- If the student writes in Tamil script (Unicode) → reply in Tamil.
- If the student writes multiple Tamil words in English letters (Tanglish like "epdi sollu", "naan venum") → reply in Tanglish.
- If the student writes in Hindi/Hinglish → reply in Hindi/Hinglish.
- If student says "speak in tamil" or "tamil la pesu" → switch to Tanglish.
- A message like "hi", "hello", "what is CMA", "I need batch date", "foundation" = ENGLISH. Reply in English.
- Do NOT switch language mid-conversation unless the student switches first.

ANTI-MIXING: Never mix Tamil and Hindi words. Never use asterisks, bold, or markdown headers.

LENGTH: 2-4 sentences for general answers. For batch/fee queries, list ALL batch entries from the live data — never truncate the list. Always complete your sentence. Never cut off mid-list.

NEVER: invent fees, dates, batch details, or guarantees.
ALWAYS: when live data shows "UPCOMING BATCHES FROM ARIVUPRO", list every batch with its date, timing, location, and fee.
When live data says "BATCH ALREADY STARTED/ENDED" or "NOTE: No upcoming batches found": tell the student clearly that batch has already started or ended, mention the fee from the record if available, and ask them to contact ArivuPro or visit arivupro.com for the next confirmed date.
NEVER present a past date (e.g. June 2024) as an upcoming batch. NEVER say "batches start regularly".

BATCH QUERY FLOW — follow this exact sequence, one question per turn:

STEP 1 — Course disambiguation (only if ambiguous):
- Student asks "CMA" with no qualifier → ask: "CMA India or CMA USA?"
- Student asks CA / ACCA / CFA / FRM / CS → go to Step 2 directly (no ambiguity)

STEP 2 — Level (only if not already stated):
- CA or CMA India → ask: "Which level — Foundation, Inter, or Final?"
- CMA USA → ask: "Part 1 or Part 2?"
- CFA → ask: "Level 1, 2, or 3?"
- ACCA → ask: "Which papers or level are you targeting?"
- If student says "any level" or "all levels" → show dates for ALL levels, then go to Step 3.

STEP 3 — Show batch dates immediately from live data, then ask location:
- List the batch dates, timing, and fee from the live data provided.
- After listing, ask: "Would you prefer Chennai classroom or Live Online?"
- Do NOT ask location before showing dates.

RULES:
- Never invent dates or fees — only show what is in the live data.
- Never say "batches start regularly" — always show actual dates.
- If live data has no results for the exact level, show all available batches and note it.
- Ask only ONE question per turn. Do not stack multiple questions in one reply.`;

// ─── Helpers ──────────────────────────────────────────────────────────────────

// AbortSignal.timeout is unreliable on Node/Windows — use Promise.race instead
function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    p,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(`Timeout after ${ms}ms`)), ms)
    ),
  ]);
}

async function geminiCall(
  key: string,
  prompt: string,
  maxTokens: number,
  temperature: number
): Promise<string | null> {
  const makeBody = () => JSON.stringify({
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: { maxOutputTokens: maxTokens, temperature },
  });
  // Try primary model first, fall back to lite on rate limit / error
  const MODELS = [
    'gemini-3.5-flash',
    'gemini-3.5-flash-lite',
  ];
  let res: Response | null = null;
  for (const model of MODELS) {
    try {
      const r = await withTimeout(
        fetch(
          `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}`,
          { method: "POST", headers: { "Content-Type": "application/json" }, body: makeBody() }
        ),
        12000
      );
      if (r.status === 429 || r.status === 503) continue; // try next model
      res = r;
      break;
    } catch {
      // timeout or network error — try next model
      continue;
    }
  }
  if (!res || !res.ok) return null;
  const data = await res.json() as {
    candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
  };
  return (
    data.candidates?.[0]?.content?.parts?.map((p) => p.text || "").join("") ||
    null
  );
}

// Tanglish = Tamil words written in English letters. Must NOT include generic English words
// like "batch", "course", "level", "super", "chance", "bro", "sir", "da", "di" — those
// appear in plain English sentences and cause false positive language detection.
const TANGLISH_TOKENS = /\b(pathi|venum|epdi|iruku|irukku|naan|enna|yenna|sollu|solu|theriyum|therila|konjam|romba|vera level|machi|enga|unga|inga|onga|panna|panrom|aachu|illa|illai|thaan|aiyo|adei|machan|ennada|yov|serthuk|evlo|aaagum|serunga|vanakkam|eppo|yeppov|ethu|enna panna|sollunga|theriyuma|therila|romba nalla)\b/i;
const HINGLISH_TOKENS = /\b(kya|hai|hain|mujhe|aap|kaise|chahiye|batao|bata|karo|karein|accha|theek|bilkul|zaroor|bohot|bahut|sirf|abhi|pehle|baad|lekin|toh|nahi|kyun|kab|kahan|kaun|kitna|kitne)\b/i;

function isNonEnglish(text: string): boolean {
  // Non-ASCII script characters = definitely non-English
  if (/[^\x00-\x7F]/.test(text)) return true;
  // Only flag as Tanglish/Hinglish if there are MULTIPLE tokens or very specific ones
  // A single ambiguous word doesn't count
  const tanglishMatches = text.match(new RegExp(TANGLISH_TOKENS.source, 'gi')) || [];
  if (tanglishMatches.length >= 2) return true;
  if (HINGLISH_TOKENS.test(text)) return true;
  return false;
}

function detectLanguage(text: string): string {
  if (/[஀-௿]/.test(text)) return "ta";
  if (/[ऀ-ॿ]/.test(text)) return "hi";
  const tanglishMatches = text.match(new RegExp(TANGLISH_TOKENS.source, 'gi')) || [];
  if (tanglishMatches.length >= 2) return "tanglish";
  if (HINGLISH_TOKENS.test(text)) return "hinglish";
  return "en";
}

function buildCalendlyUrl(
  baseUrl: string,
  data: CollectedData
): string {
  const params = new URLSearchParams();
  if (data.name) params.set("name", data.name);
  if (data.email) params.set("email", data.email);
  params.set("hide_gdpr_banner", "1");
  params.set("primary_color", "2e8857");
  const qs = params.toString();
  return qs ? `${baseUrl}?${qs}` : baseUrl;
}

async function geminiSTT(key: string, audioBase64: string): Promise<string> {
  const sttBody = (model: string) => JSON.stringify({
    contents: [{
      parts: [
        { text: 'Transcribe this audio exactly as spoken. Return only the transcription text, nothing else.' },
        { inline_data: { mime_type: 'audio/webm', data: audioBase64 } }
      ]
    }],
    generationConfig: { maxOutputTokens: 300, temperature: 0 }
  });
  // Try gemini-2.5-flash first (best for audio), then lite fallback — both with hard timeouts
  for (const model of ['gemini-2.5-flash', 'gemini-3.5-flash-lite']) {
    try {
      const res = await withTimeout(
        fetch(
          `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: sttBody(model) }
        ),
        10000
      );
      if (!res.ok) continue;
      const data = await res.json() as { candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }> };
      const text = data.candidates?.[0]?.content?.parts?.[0]?.text?.trim();
      if (text) return text;
    } catch {
      continue;
    }
  }
  return '';
}

// ─── Main handler ─────────────────────────────────────────────────────────────

export async function POST(req: Request): Promise<Response> {
  try {
    const { sessionId: _sessionId, message: rawMessage, audioBase64, isVoice, history, collectedData: rawCollected, sessionMeta: rawMeta } = (await req.json()) as BotRequestBody;

    const key = process.env.GEMINI_API_KEY;
    if (!key) {
      return Response.json(
        { error: "Gemini API key not configured." },
        { status: 503 }
      );
    }

    // STT: if audio provided, transcribe first
    let message = rawMessage || '';
    if (audioBase64 && key) {
      const transcript = await geminiSTT(key, audioBase64);
      if (transcript) message = transcript;
    }
    if (!message.trim()) {
      return Response.json({ error: "No message received." }, { status: 400 });
    }

    // ── 1. Extract & merge slots ────────────────────────────────────────────
    // Only auto-extract phone/email from general messages (unambiguous signals).
    // Name is NEVER auto-extracted from conversation — only accepted when the
    // frontend is in active collection mode (rawCollected.__collecting === 'name').
    const incomingSlots = extractSlots(message);
    const safeIncoming: CollectedData = {
      phone: incomingSlots.phone,
      email: incomingSlots.email,
      course: incomingSlots.course,
      // name only accepted if the frontend explicitly flagged it is collecting name
      name: (rawCollected as CollectedData & { __collecting?: string })?.__collecting === 'name'
        ? incomingSlots.name
        : undefined,
    };
    const collectedData: CollectedData = mergeSlots(rawCollected ?? {}, safeIncoming);

    // ── 2. Update session meta ──────────────────────────────────────────────
    const meta: SessionMeta = {
      turnCount: (rawMeta?.turnCount ?? 0) + 1,
      noMatchCount: rawMeta?.noMatchCount ?? 0,
      repeatCount: rawMeta?.repeatCount ?? 0,
      cumulativeEscalationScore: rawMeta?.cumulativeEscalationScore ?? 0,
    };

    // ── 3. Explicit escalation check ────────────────────────────────────────
    const explicitRequest = detectExplicitEscalation(message);

    // ── 4. Language detection ───────────────────────────────────────────────
    const nonEnglish = isNonEnglish(message);
    const language = detectLanguage(message);
    const langLabel: Record<string, string> = {
      ta: "Tamil script",
      hi: "Hindi",
      tanglish: "Tanglish (Tamil words in English letters — ZERO Hindi words allowed)",
      hinglish: "Hinglish (Hindi words in English letters)",
      en: "English only",
    };

    // ── 4b. FAST PATH: explicit escalation request — skip AI, go straight to booking ──
    // When student says "I need to connect a call", "want to talk", "book a meeting" etc.,
    // never answer with a text reply. Immediately start the booking flow.
    if (explicitRequest) {
      const escReplies: Record<string, string> = {
        en: "Absolutely! Let me connect you with our counselling team right away. I'll just need a couple of details to book your free session.",
        ta: "நிச்சயமாக! உங்களை எங்கள் counsellor கிட்ட connect பண்றேன். ஒரு free session book பண்ண கொஞ்சம் details சொல்லுங்க.",
        tanglish: "Sure da! Ungaluku oru free counselling session book pannalam. Konjam details sollunga — counsellor kitta directly connect pannuren!",
        hinglish: "Bilkul! Main aapko hamare counselling team se connect karta hoon. Ek free session book karne ke liye thoda details chahiye.",
        hi: "बिल्कुल! मैं आपको हमारी counselling team से connect करता हूं। एक free session book करने के लिए थोड़ी details चाहिए।",
      };
      const escReply = escReplies[language] || escReplies.en;

      let escAction: BotAction = "answer";
      if (!collectedData.name) escAction = "collect_name";
      else if (!collectedData.phone) escAction = "collect_phone";
      else if (!collectedData.email) escAction = "collect_email";
      else escAction = "show_calendly";

      let escCalendlyUrl: string | undefined;
      if (escAction === "show_calendly") {
        const base = process.env.NEXT_PUBLIC_CALENDLY_URL || "https://calendly.com/tech-arivupro/30min";
        escCalendlyUrl = buildCalendlyUrl(base, collectedData);
      }

      const thisScore = calculateEscalationScore({
        sentimentScore: 0.8,
        noMatchCount: meta.noMatchCount,
        repeatCount: meta.repeatCount,
        explicitRequest: true,
        turnCount: meta.turnCount,
      });
      meta.cumulativeEscalationScore += thisScore * 0.4;

      return Response.json({
        reply: escReply,
        action: escAction,
        escalationScore: thisScore,
        cumulativeScore: meta.cumulativeEscalationScore,
        collectedData,
        sessionMeta: meta,
        language,
        source: "gemini",
        ...(escCalendlyUrl ? { calendlyUrl: escCalendlyUrl } : {}),
      } as BotResponse);
    }

    // ── 4c. Fetch WP data + run classifier ALL in parallel ──────────────────
    // Classifier has zero dependency on WP data — run all three concurrently.
    const classifyPrompt = `You are a classifier. A student asked this question (may be in any Indian language or mix):
"${message}"

Below are counselling script topics. If the student's question is essentially about the SAME topic as one of these scripts (even if worded differently or in another language), reply with ONLY: MATCH:<id>
If the question does not match any script, reply with ONLY: NO_MATCH

Scripts:
${scriptIndex}

Reply with one line only — either MATCH:<id> or NO_MATCH.`;

    // Hard 6s cap — if WP/DB fetches hang (Cloudflare, cold DB), classifier
    // result still arrives in time and we proceed with empty WP context.
    const timeout = <T>(p: Promise<T>, ms: number): Promise<T | null> =>
      Promise.race([p, new Promise<null>(res => setTimeout(() => res(null), ms))]);

    const [wpDbEarly, wpLiveEarly, classifyResult] = await Promise.all([
      timeout(lookupWpData(message), 5000).catch(() => null),
      timeout(fetchWordPressContext(message, collectedData.course), 7000).catch(() => null),
      timeout(geminiCall(key, classifyPrompt, 20, 0.1), 8000).catch(() => null),
    ]);
    const wpDbContent = typeof wpDbEarly === "string" ? wpDbEarly : "";
    const wpLiveContent = typeof wpLiveEarly === "string" ? wpLiveEarly : "";
    const wpContentEarly = [wpDbContent, wpLiveContent].filter(Boolean).join("\n\n");
    const classification = typeof classifyResult === "string" ? classifyResult : null;

    // ── 5. Check classifier result ──────────────────────────────────────────

    let reply = "";
    let source: BotResponse["source"] = "gemini";
    let sentimentScore = 0.1; // default: neutral

    const trimmed = classification?.trim() ?? "";

    if (trimmed.startsWith("MATCH:")) {
      // ── 6. Curated script path ────────────────────────────────────────────
      const matchedId = trimmed.replace("MATCH:", "").trim();
      const script = talkingPoints.find((p) => p.id === matchedId);

      if (script) {
        const courseName = collectedData.course || "the course you are considering";
        const rawAnswer = script.answer.replace(/\{course\}/g, courseName);
        const rawFollowups = script.followups.map((f, i) => `${i + 1}. ${f}`).join("\n");
        const rawVerify = script.verify;
        const wpInject = wpContentEarly
          ? `\n\nLIVE BATCH/FEE DATA FROM ARIVUPRO WEBSITE:\n${wpContentEarly}\nUse this data to fill in accurate batch dates or fees if the student asked about them.`
          : "";

        if (nonEnglish) {
          const translatePrompt = `Student asked (in ${langLabel[language] || language}): "${message}"

Adapt this counsellor response into the EXACT language the student used RIGHT NOW: ${langLabel[language] || language}.
Rules: Sound like a knowledgeable friend texting — short, crisp, under 80 words. No headers. No asterisks. Just natural.
${language === 'tanglish' ? 'TANGLISH ONLY: Use Tamil-origin words in English letters. NEVER use Hindi words like kaise/batao/accha/theek.' : ''}
${language === 'hinglish' ? 'HINGLISH ONLY: Use Hindi-origin words in English letters. Do not mix Tamil.' : ''}
${wpInject}

Answer: ${rawAnswer}
Follow-ups: ${rawFollowups}
Verify: ${rawVerify}`;

          const translated = await geminiCall(key, translatePrompt, 1200, 0.4);
          reply = translated ?? rawAnswer;
        } else {
          reply = `${rawAnswer}\n\n${rawFollowups}`;
        }

        source = "curated";
        sentimentScore = 0.1; // positive interaction, low escalation signal
        // noMatchCount stays the same
      }
    }

    if (!reply) {
      // ── 7. NO_MATCH path — WP lookup + full Gemini answer ─────────────────
      meta.noMatchCount += 1;

      // Reuse the WP data already fetched above
      const wpContent = wpContentEarly;

      const wpSection = wpContent
        ? `\n\nLIVE DATA FROM ARIVUPRO WEBSITE (batch dates, fees, schedules — use this):\n${wpContent}\n`
        : "";

      // Build conversation history snippet (last 10 turns)
      const historySnippet = (history ?? [])
        .slice(-10)
        .map((h) => `${h.role === "student" ? "Student" : "Arivu"}: ${h.content}`)
        .join("\n");
      const historySection = historySnippet
        ? `\n\nCONVERSATION SO FAR:\n${historySnippet}\n`
        : "";

      // Explicit per-turn language override — prevents history context from bleeding language
      const currentLangInstruction = `\n\nCURRENT MESSAGE LANGUAGE: ${langLabel[language] || "English"}.
THIS TURN RULE: You MUST reply in ${langLabel[language] || "English"}. Ignore the language of previous turns in history — reply only to the language of the CURRENT message above.`;

      const fullPrompt = `${BOT_SYSTEM}

ABOUT ARIVUPRO:
${ARIVUPRO_BASE}
${wpSection}${historySection}${currentLangInstruction}

Student: ${message}
Arivu:`;

      const rawGeminiResponse = await geminiCall(key, fullPrompt, 1200, 0.35);

      if (!rawGeminiResponse) {
        return Response.json(
          { error: "AI service could not respond right now." },
          { status: 502 }
        );
      }

      // ── 8. Parse JSON response, fallback to plain text ────────────────────
      // Plain text response — strip any accidental markdown and use directly
      reply = rawGeminiResponse
        .replace(/^```[\w]*\n?/m, "")
        .replace(/\n?```$/m, "")
        .trim();

      sentimentScore = parseSentimentScore("neutral");
      source = wpContent ? "wp" : "gemini";
      // source reflects primary data used
    }

    // ── 9. Calculate escalation scores ──────────────────────────────────────
    const thisScore = calculateEscalationScore({
      sentimentScore,
      noMatchCount: meta.noMatchCount,
      repeatCount: meta.repeatCount,
      explicitRequest,
      turnCount: meta.turnCount,
    });

    // Rolling cumulative: previous + (thisScore * 0.4)
    const cumulativeScore = meta.cumulativeEscalationScore + thisScore * 0.4;
    meta.cumulativeEscalationScore = cumulativeScore;

    // ── 10. Determine action ─────────────────────────────────────────────────
    let action: BotAction = "answer";
    let calendlyUrl: string | undefined;

    if (cumulativeScore > ESCALATION_THRESHOLD || explicitRequest) {
      if (!collectedData.name) {
        action = "collect_name";
      } else if (!collectedData.phone) {
        action = "collect_phone";
      } else if (!collectedData.email) {
        action = "collect_email";
      } else {
        action = "show_calendly";
      }
    }

    // ── 11. Build Calendly URL if needed ─────────────────────────────────────
    if (action === "show_calendly") {
      const baseCalendlyUrl =
        process.env.NEXT_PUBLIC_CALENDLY_URL || "https://calendly.com/tech-arivupro/30min";
      calendlyUrl = buildCalendlyUrl(baseCalendlyUrl, collectedData);
    }

    // TTS: do NOT pre-generate inline — it adds 3-4s to every reply.
    // The Speak button calls /api/bot-tts (streaming) on demand, which is fast enough.
    const replyAudio: string | null = null;

    // ── 12. Return full response ──────────────────────────────────────────────
    const response: BotResponse = {
      reply,
      action,
      escalationScore: thisScore,
      cumulativeScore,
      collectedData,
      sessionMeta: meta,
      language,
      source,
      ...(calendlyUrl ? { calendlyUrl } : {}),
      ...(replyAudio !== null ? { replyAudio } : {}),
    };

    return Response.json(response);
  } catch (err) {
    console.error("[bot/route] Unhandled error:", err);
    return Response.json(
      { error: "Unable to process your message right now." },
      { status: 500 }
    );
  }
}
