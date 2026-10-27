import {getChatGPTUser} from "../../chatgpt-auth";
import {talkingPoints} from "@/lib/counselling-answers";
import {fetchWordPressContext} from "@/lib/wordpress";
export const dynamic="force-dynamic";

const system = `You are a counsellor at ArivuPro Academy. You reply like a knowledgeable senior friend texting back — SHORT, CRISP, and helpful.

LANGUAGE RULE — CRITICAL:
Reply in the EXACT same language/mix the student used.
- Tamil → Tamil | Hindi → Hindi | Tanglish → Tanglish | Hinglish → Hinglish | English → English
- Sound like a native speaker texting, NOT a formal document.

LENGTH RULE — CRITICAL:
Keep the entire reply under 120 words. Student is reading on mobile. No long paragraphs.
Use this format:
[1-2 line direct answer]

[3–5 bullet points max — only the most important facts]

[1 line ArivuPro plug]

[2 short follow-up questions]

[1 line: what to verify]

RULES:
- Never invent fees, dates, pass rates or placement guarantees
- CA Foundation: 4 papers, May/Nov exams, ICAI registration
- CMA India (ICMAI) ≠ US CMA (IMA) — always clarify if relevant
- Mark changing facts: "Verify with ICAI/ArivuPro team"
- No headers like "Key details:" or "Verification note:" — just write naturally`;

async function geminiCall(key: string, prompt: string, maxTokens: number, temperature: number): Promise<string | null> {
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${key}`,
    {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        contents: [{parts: [{text: prompt}]}],
        generationConfig: {maxOutputTokens: maxTokens, temperature},
      }),
    }
  );
  if (!res.ok) return null;
  const data = await res.json() as {candidates?: Array<{content?: {parts?: Array<{text?: string}>}}>};
  return data.candidates?.[0]?.content?.parts?.map(p => p.text || "").join("") || null;
}

// Detect if the question is non-English (Tamil/Hindi/Telugu script chars or Tanglish/Hinglish keywords)
function isNonEnglish(text: string): boolean {
  // Non-ASCII characters = Indian language scripts (Tamil, Hindi, Telugu, Malayalam etc.)
  if (/[^\x00-\x7F]/.test(text)) return true;
  // Common Tanglish words
  if (/\b(pathi|venum|epdi|iruku|irukku|naan|enna|yenna|sollu|solu|theriyum|therila|konjam|romba|super|chance|vera|level|machi|da|di|bro|anna|akka|sir|madam|enga|unga|inga|onga|arivupro|batch|course|panna|panrom|aachu|illa|illai|thaan|than)\b/i.test(text)) return true;
  // Common Hinglish words
  if (/\b(kya|hai|hain|mujhe|aap|kaise|chahiye|batao|bata|karo|karein|accha|theek|bilkul|zaroor|bohot|bahut|sirf|abhi|pehle|baad|lekin|aur|ya|toh|na|nahi|kyun|kab|kahan|kaun|kitna|kitne)\b/i.test(text)) return true;
  return false;
}

// Build a compact script index for the classifier prompt
const scriptIndex = talkingPoints.map((p, i) => `${i}. [${p.id}] ${p.title}`).join("\n");

export async function POST(req: Request) {
  const user = await getChatGPTUser();
  if (!user) return Response.json({error: "Sign in to use the counsellor AI."}, {status: 401});
  if (!["marketing@arivupro.com", "tech@arivupro.com"].includes(user.email.toLowerCase()))
    return Response.json({error: "Counsellor access required."}, {status: 403});

  try {
    const b = await req.json() as {course?: string; level?: string; question?: string};
    if (!b.question?.trim()) return Response.json({error: "Enter a student question."}, {status: 400});

    const key = process.env.GEMINI_API_KEY;
    if (!key) return Response.json({error: "Gemini API key is not configured. Add GEMINI_API_KEY to your .env file."}, {status: 503});

    const course = b.course || "the course you are considering";
    const nonEnglish = isNonEnglish(b.question);

    // Step 1 — Gemini classifies: does this question match any curated script?
    const classifyPrompt = `You are a classifier. A student asked this question (may be in any Indian language or mix):
"${b.question}"

Below are 15 counselling script topics. If the student's question is essentially about the SAME topic as one of these scripts (even if worded differently or in another language), reply with ONLY: MATCH:<id>
If the question does not match any script, reply with ONLY: NO_MATCH

Scripts:
${scriptIndex}

Reply with one line only — either MATCH:<id> or NO_MATCH.`;

    const classification = await geminiCall(key, classifyPrompt, 20, 0.1);

    if (classification) {
      const trimmed = classification.trim();
      if (trimmed.startsWith("MATCH:")) {
        const matchedId = trimmed.replace("MATCH:", "").trim();
        const script = talkingPoints.find(p => p.id === matchedId);
        if (script) {
          const rawAnswer = script.answer.replace(/\{course\}/g, course);
          const rawFollowups = script.followups.map((f, i) => `${i + 1}. ${f}`).join("\n");
          const rawVerify = script.verify;

          // Non-English question — translate the curated script into student's language/style
          if (nonEnglish) {
            const translatePrompt = `Student asked: "${b.question}"

Adapt this counsellor response into the EXACT same language/mix the student used. Sound like a senior friend texting — short, crisp, under 100 words total. No formal headers. Just natural.

Answer: ${rawAnswer}
Follow-ups: ${rawFollowups}
Verify: ${rawVerify}`;

            const translated = await geminiCall(key, translatePrompt, 1200, 0.4);
            if (translated) {
              return Response.json({answer: translated, source: "curated", scriptTitle: script.title});
            }
          }

          // English — return curated script as-is
          const full = `${rawAnswer}\n\n**Follow-up questions to ask the student:**\n${rawFollowups}\n\n**Before sharing:** ${rawVerify}`;
          return Response.json({answer: full, source: "curated", scriptTitle: script.title});
        }
      }
    }

    // Step 2 — No curated match — fetch live WordPress context + full Gemini answer
    const wpContext = await fetchWordPressContext(b.question);
    const wpSection = wpContext
      ? `\n\nLive data from ArivuPro website (use this for batch/fee/schedule questions):\n${wpContext}\n`
      : "";

    const prompt = `${system}${wpSection}\n\nCourse: ${course}\nLevel: ${b.level || "Not specified"}\nStudent question: ${b.question}\n\nIMPORTANT: Detect the student's language/mix from their question above and reply in that EXACT same language and style throughout your entire answer. Do not cut off — finish the full response.`;

    const geminiAnswer = await geminiCall(key, prompt, 2000, 0.35);

    if (!geminiAnswer) {
      return Response.json({error: "Gemini service could not answer right now."}, {status: 502});
    }

    return Response.json({answer: geminiAnswer, source: "gemini"});

  } catch {
    return Response.json({error: "Unable to generate an answer right now."}, {status: 500});
  }
}
