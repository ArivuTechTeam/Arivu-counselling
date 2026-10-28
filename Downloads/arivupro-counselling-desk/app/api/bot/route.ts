import { talkingPoints } from "@/lib/counselling-answers";
import { scriptIndex, lookupWpData } from "@/lib/bot-knowledge";
import { extractSlots, mergeSlots } from "@/lib/slot-filler";
import {
  calculateEscalationScore,
  detectExplicitEscalation,
  parseSentimentScore,
  ESCALATION_THRESHOLD,
} from "@/lib/escalation";

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

LANGUAGE RULE — CRITICAL: Detect what language the student wrote in and reply in that EXACT same language or mix.
- English only → reply only in English
- Tamil script → reply in Tamil
- Tanglish (Tamil words in English letters like "pesu", "venum", "sollu") → reply in Tanglish
- Hindi → reply in Hindi
- Hinglish → reply in Hinglish
- If student says "speak in tamil" or "tamil la pesu" → switch to Tanglish/Tamil immediately

LENGTH: Max 80 words. No markdown, no asterisks, no headers. Plain conversational text only.
Format: 1-2 line direct answer, 2-3 short points, 1 follow-up question.

NEVER: invent fees, dates, batch details, or guarantees.
ALWAYS: use provided live data for batch dates and fees if available.`;

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function geminiCall(
  key: string,
  prompt: string,
  maxTokens: number,
  temperature: number
): Promise<string | null> {
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${key}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { maxOutputTokens: maxTokens, temperature },
      }),
    }
  );
  if (!res.ok) return null;
  const data = await res.json() as {
    candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
  };
  return (
    data.candidates?.[0]?.content?.parts?.map((p) => p.text || "").join("") ||
    null
  );
}

function isNonEnglish(text: string): boolean {
  // Non-ASCII characters = Indian language scripts (Tamil, Hindi, Telugu, Malayalam etc.)
  if (/[^\x00-\x7F]/.test(text)) return true;
  // Common Tanglish words
  if (
    /\b(pathi|venum|epdi|iruku|irukku|naan|enna|yenna|sollu|solu|theriyum|therila|konjam|romba|super|chance|vera|level|machi|da|di|bro|anna|akka|sir|madam|enga|unga|inga|onga|arivupro|batch|course|panna|panrom|aachu|illa|illai|thaan|than)\b/i.test(
      text
    )
  )
    return true;
  // Common Hinglish words
  if (
    /\b(kya|hai|hain|mujhe|aap|kaise|chahiye|batao|bata|karo|karein|accha|theek|bilkul|zaroor|bohot|bahut|sirf|abhi|pehle|baad|lekin|aur|ya|toh|na|nahi|kyun|kab|kahan|kaun|kitna|kitne)\b/i.test(
      text
    )
  )
    return true;
  return false;
}

function detectLanguage(text: string): string {
  if (/[஀-௿]/.test(text)) return "ta"; // Tamil script
  if (/[ऀ-ॿ]/.test(text)) return "hi"; // Devanagari (Hindi)
  if (
    /\b(pathi|venum|epdi|iruku|irukku|naan|enna|yenna|sollu|solu|theriyum|therila|konjam|romba|machi|da|di|anna|akka|enga|unga|inga)\b/i.test(
      text
    )
  )
    return "tanglish";
  if (
    /\b(kya|hai|hain|mujhe|aap|kaise|chahiye|batao|bohot|bahut|sirf|abhi|lekin|aur|nahi|kyun|kab|kahan)\b/i.test(
      text
    )
  )
    return "hinglish";
  return "en";
}

function buildCalendlyUrl(
  baseUrl: string,
  data: CollectedData
): string {
  const params = new URLSearchParams();
  if (data.name) params.set("name", data.name);
  if (data.email) params.set("email", data.email);
  if (data.phone) params.set("a1", data.phone);
  const qs = params.toString();
  return qs ? `${baseUrl}?${qs}` : baseUrl;
}

async function geminiSTT(key: string, audioBase64: string): Promise<string> {
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${key}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{
          parts: [
            { text: 'Transcribe this audio exactly as spoken. Return only the transcription, nothing else.' },
            { inline_data: { mime_type: 'audio/ogg', data: audioBase64 } }
          ]
        }],
        generationConfig: { maxOutputTokens: 200, temperature: 0 }
      })
    }
  );
  if (!res.ok) return '';
  const data = await res.json() as { candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }> };
  return data.candidates?.[0]?.content?.parts?.[0]?.text?.trim() || '';
}

async function geminiTTS(key: string, text: string): Promise<string | null> {
  // Gemini 2.5 Flash TTS
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key=${key}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text }] }],
        generationConfig: {
          response_modalities: ['AUDIO'],
          speech_config: {
            voice_config: { prebuilt_voice_config: { voice_name: 'Aoede' } }
          }
        }
      })
    }
  );
  if (!res.ok) return null;
  const data = await res.json() as { candidates?: Array<{ content?: { parts?: Array<{ inline_data?: { data?: string } }> } }> };
  return data.candidates?.[0]?.content?.parts?.[0]?.inline_data?.data || null;
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
    const incomingSlots = extractSlots(message);
    const collectedData: CollectedData = mergeSlots(rawCollected ?? {}, incomingSlots);

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

    // ── 5. Gemini classifier: match curated script? ─────────────────────────
    const classifyPrompt = `You are a classifier. A student asked this question (may be in any Indian language or mix):
"${message}"

Below are counselling script topics. If the student's question is essentially about the SAME topic as one of these scripts (even if worded differently or in another language), reply with ONLY: MATCH:<id>
If the question does not match any script, reply with ONLY: NO_MATCH

Scripts:
${scriptIndex}

Reply with one line only — either MATCH:<id> or NO_MATCH.`;

    const classification = await geminiCall(key, classifyPrompt, 20, 0.1);

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

        if (nonEnglish) {
          const translatePrompt = `Student asked: "${message}"

Adapt this counsellor response into the EXACT same language/mix the student used. Sound like a knowledgeable friend texting — short, crisp, under 80 words. No formal headers. Just natural.

Answer: ${rawAnswer}
Follow-ups: ${rawFollowups}
Verify: ${rawVerify}`;

          const translated = await geminiCall(key, translatePrompt, 600, 0.4);
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

      const wpContent = await lookupWpData(message);
      const wpSection = wpContent
        ? `\n\nLIVE ARIVUPRO COURSE DATA (use this for fees, batch dates, schedules):\n${wpContent}\n`
        : "";

      // Build conversation history snippet (last 10 turns)
      const historySnippet = (history ?? [])
        .slice(-10)
        .map((h) => `${h.role === "student" ? "Student" : "Arivu"}: ${h.content}`)
        .join("\n");
      const historySection = historySnippet
        ? `\n\nCONVERSATION SO FAR:\n${historySnippet}\n`
        : "";

      const fullPrompt = `${BOT_SYSTEM}${wpSection}${historySection}

Student: ${message}

IMPORTANT: Your entire response must be ONLY a valid JSON object on a single line, no other text before or after it.
Format: {"reply":"your answer here","sentiment":"neutral"}
Sentiment options: positive, neutral, mild_negative, negative, strong_negative, distress
No markdown, no code fences, no explanation — just the raw JSON object.`;

      const rawGeminiResponse = await geminiCall(key, fullPrompt, 600, 0.35);

      if (!rawGeminiResponse) {
        return Response.json(
          { error: "AI service could not respond right now." },
          { status: 502 }
        );
      }

      // ── 8. Parse JSON response, fallback to plain text ────────────────────
      let parsedSentiment = "neutral";
      try {
        // Strip markdown code fences if present
        const jsonStr = rawGeminiResponse
          .replace(/^```(?:json)?\s*/i, "")
          .replace(/\s*```$/, "")
          .trim();
        // Extract JSON object even if there's surrounding text
        const jsonMatch = jsonStr.match(/\{[\s\S]*\}/);
        const parsed = JSON.parse(jsonMatch?.[0] ?? jsonStr) as { reply?: string; sentiment?: string };
        reply = parsed.reply?.trim() || rawGeminiResponse.trim();
        parsedSentiment = parsed.sentiment?.trim() || "neutral";
      } catch {
        // Gemini returned plain text — use it directly
        reply = rawGeminiResponse.trim();
        parsedSentiment = "neutral";
      }

      sentimentScore = parseSentimentScore(parsedSentiment);
      source = wpContent ? "wp" : "gemini";
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
        process.env.NEXT_PUBLIC_CALENDLY_URL || "https://calendly.com/arivupro";
      calendlyUrl = buildCalendlyUrl(baseCalendlyUrl, collectedData);
    }

    // TTS: generate audio for voice responses
    let replyAudio: string | null = null;
    if (isVoice && key && reply) {
      replyAudio = await geminiTTS(key, reply);
    }

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
