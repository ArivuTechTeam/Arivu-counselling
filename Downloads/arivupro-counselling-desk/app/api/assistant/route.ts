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
  for (const model of ['gemini-3.5-flash', 'gemini-3.5-flash-lite']) {
    try {
      const res = await Promise.race([
        fetch(
          `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}`,
          {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              contents: [{parts: [{text: prompt}]}],
              generationConfig: {maxOutputTokens: maxTokens, temperature},
            }),
          }
        ),
        new Promise<never>((_, reject) => setTimeout(() => reject(new Error('timeout')), 12000)),
      ]);
      if (!res.ok) continue;
      const data = await res.json() as {candidates?: Array<{content?: {parts?: Array<{text?: string}>}}>};
      const text = data.candidates?.[0]?.content?.parts?.map(p => p.text || "").join("") || null;
      if (text) return text;
    } catch { continue; }
  }
  return null;
}

// Detect non-English — requires clear Tamil/Hindi signals, not generic English words
function isNonEnglish(text: string): boolean {
  if (/[^\x00-\x7F]/.test(text)) return true;
  // Tanglish: needs 2+ unambiguous Tamil-origin words (not generic English like batch/course/sir)
  const tanglish = /\b(pathi|venum|epdi|iruku|irukku|naan|enna|yenna|sollu|solu|theriyum|therila|konjam|romba|machi|enga|unga|inga|panna|panrom|aachu|illa|illai|thaan|aiyo|adei|ennada|serthuk|evlo|aaagum|serunga|vanakkam|eppo|theriyuma)\b/gi;
  if ((text.match(tanglish) || []).length >= 2) return true;
  // Hinglish: single clear Hindi word is enough
  if (/\b(kya|hai|hain|mujhe|aap|kaise|chahiye|batao|bata|karo|karein|accha|theek|bilkul|zaroor|bohot|bahut|abhi|pehle|baad|lekin|nahi|kyun|kab|kahan|kaun|kitna|kitne)\b/i.test(text)) return true;
  return false;
}

function needsLiveWebsiteData(text: string): boolean {
  return /\b(fee|fees|price|cost|batch|start|starts|starting|schedule|timing|date|available|availability|offer|discount|admission|enrol|enroll|join)\b/i.test(text)
    || /[\u0B80-\u0BFF\u0900-\u097F]/.test(text);
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
    const liveQuestion = needsLiveWebsiteData(b.question);

    // Step 1 — Gemini classifies: does this question match any curated script?
    const classifyPrompt = `You are a classifier. A student asked this question (may be in any Indian language or mix):
"${b.question}"

Below are 15 counselling script topics. If the student's question is essentially about the SAME topic as one of these scripts (even if worded differently or in another language), reply with ONLY: MATCH:<id>
If the question does not match any script, reply with ONLY: NO_MATCH

Scripts:
${scriptIndex}

Reply with one line only — either MATCH:<id> or NO_MATCH.`;

    const classification = liveQuestion ? null : await geminiCall(key, classifyPrompt, 20, 0.1);

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
    // fetchWordPressContext(query, course) — pass level+question together so filter picks correct level
    const wpContext = await fetchWordPressContext(`${b.level || ''} ${b.question}`, course);
    const wpSection = wpContext
      ? `\n\nLIVE ARIVUPRO COURSE DATA (the only source for current batch details):\n${wpContext}\n`
      : "";

    const prompt = `${system}${wpSection}\n\nCourse: ${course}\nLevel: ${b.level || "Not specified"}\nStudent question: ${b.question}\n\nCURRENT-DATA RULE: For batch dates, fees, timings, locations, modes, exam attempts, and availability, use only the LIVE ARIVUPRO COURSE DATA above. Never use general knowledge, old dates, or guesses. If a requested field is empty or absent, say that the exact detail is not available in the live website data and offer a counsellor. Do not write vague dates such as "early November" when no exact date is present.\nIMPORTANT: Detect the student's language/mix from their question above and reply in that EXACT same language and style throughout your entire answer. Do not cut off — finish the full response.`;

    const geminiAnswer = await geminiCall(key, prompt, 2000, 0.35);

    if (!geminiAnswer) {
      return Response.json({error: "Gemini service could not answer right now."}, {status: 502});
    }

    return Response.json({answer: geminiAnswer, source: liveQuestion ? "live-website" : "gemini"});

  } catch {
    return Response.json({error: "Unable to generate an answer right now."}, {status: 500});
  }
}
