import {getChatGPTUser} from "../../chatgpt-auth";
import {talkingPoints} from "@/lib/counselling-answers";
import {fetchWordPressContext, formatCoursesForBot} from "@/lib/wordpress";
export const dynamic="force-dynamic";

const system = `You are an AI briefing tool for ArivuPro Academy counsellors. You are NOT talking to the student — you are giving the counsellor a ready-to-use briefing so they can answer the student confidently.

OUTPUT FORMAT (always follow this exactly):

STUDENT'S QUESTION SUMMARY
One line restating what the student wants to know.

ANSWER TO GIVE THE STUDENT
2-4 sentences the counsellor can say directly to the student. Conversational, not robotic.
If live batch data is available, include the exact start date, timing, location, fee — no vague statements.

KEY FACTS
• Fact 1
• Fact 2
• Fact 3 (3-5 bullets max — only things the counsellor needs to know)

SUGGESTED FOLLOW-UP QUESTIONS
• Question to ask the student to continue the conversation

WHAT TO VERIFY
One line on what to double-check before sharing (fees, dates, exam window etc.)

RULES:
- Never invent batch dates, fees, or guarantees — only use the live WordPress data provided
- If batch data is available, state it clearly: "Next batch starts 14 Nov 2026, 10 AM–1 PM, Chennai classroom, Fee: ₹X"
- If no live data available, say so plainly: "Batch details not in system — check with team"
- CMA India (ICMAI) ≠ CMA USA (IMA) — always clarify
- Never use asterisks or markdown bold — plain text only`;

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
    const b = await req.json() as {course?: string; level?: string; question?: string; wpData?: unknown};
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

          // English — format as counsellor briefing
          const full = `STUDENT'S QUESTION SUMMARY\n${script.title}\n\nANSWER TO GIVE THE STUDENT\n${rawAnswer}\n\nSUGGESTED FOLLOW-UP QUESTIONS\n${rawFollowups}\n\nWHAT TO VERIFY\n${rawVerify}`;
          return Response.json({answer: full, source: "curated", scriptTitle: script.title});
        }
      }
    }

    // Step 2 — No curated match — fetch live WordPress context + full Gemini answer
    // If client sent pre-fetched WP data (bypasses Railway IP block), format it directly.
    // Otherwise fall back to server-side fetch.
    let wpContext: string;
    if (Array.isArray(b.wpData) && b.wpData.length > 0) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      wpContext = formatCoursesForBot(b.wpData as any[], `${b.level || ''} ${b.question}`);
    } else {
      wpContext = await fetchWordPressContext(`${b.level || ''} ${b.question}`, course);
    }
    const wpSection = wpContext
      ? `\n\n=== LIVE BATCH DATA FROM ARIVUPRO WORDPRESS ===\n${wpContext}\n=== END LIVE DATA ===\n\nIMPORTANT: Use the live batch data above for all dates, fees, timings, and locations. Do not guess or use general knowledge for these fields.`
      : `\n\nNO LIVE BATCH DATA AVAILABLE — tell the counsellor to check with the team for current dates and fees.`;

    const prompt = `${system}${wpSection}

Course: ${course}
Level / Stage: ${b.level || 'Not specified'}
Student's question: ${b.question}

Write the counsellor briefing now:`;

    const geminiAnswer = await geminiCall(key, prompt, 2000, 0.35);

    if (!geminiAnswer) {
      return Response.json({error: "Gemini service could not answer right now."}, {status: 502});
    }

    return Response.json({answer: geminiAnswer, source: liveQuestion ? "live-website" : "gemini"});

  } catch {
    return Response.json({error: "Unable to generate an answer right now."}, {status: 500});
  }
}
