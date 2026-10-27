import {getChatGPTUser} from "../../chatgpt-auth";
import {talkingPoints} from "@/lib/counselling-answers";
export const dynamic="force-dynamic";

const system=`You are an expert Professional Commerce SME counsellor at ArivuPro Academy, one of India's leading coaching institutes for CA, CS, CMA, ACCA, CFA, FRM, EA, CPA, CFP, CIA, Class 11/12 Commerce and B.Com.

RESPONSE FORMAT — always follow this structure:
1. Direct answer (2-3 sentences addressing the question immediately)
2. Key details (bullet points with specific, actionable information)
3. ArivuPro advantage (1 sentence on how ArivuPro supports this)
4. Two follow-up questions to understand the student better
5. Verification note (what to confirm with official body or programme team)

RULES:
- Answer in clear, warm Indian English — like a knowledgeable senior friend
- Be specific and complete — never cut off mid-answer
- For CA Foundation: mention 4 papers (Accounting, Business Laws, Maths/Stats, Business Economics), twice-yearly exams (May/November), ICAI registration requirement
- For CS: mention Foundation/Executive/Professional structure, ICSI registration
- For CMA India: mention Foundation/Inter/Final structure, ICMAI, distinguish clearly from US CMA
- Never invent fees, exam dates, pass rates, salary guarantees or placement promises
- Mark time-sensitive facts as "Verify with ICAI/ICSI/ICMAI/ArivuPro team"
- Distinguish CMA India (ICMAI) from US CMA (IMA) every time both are possible`;

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

    // Step 1 — ask Gemini to classify: does this question match any curated script?
    const classifyPrompt = `You are a classifier. A student asked this question:
"${b.question}"

Below are 15 counselling script topics. If the student's question is essentially about the SAME topic as one of these scripts (even if worded differently), reply with ONLY the script id like: MATCH:fees
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
          const answer = script.answer.replace(/\{course\}/g, course);
          const followupText = script.followups.map((f, i) => `${i + 1}. ${f}`).join("\n");
          const full = `${answer}\n\n**Follow-up questions to ask the student:**\n${followupText}\n\n**Before sharing:** ${script.verify}`;
          return Response.json({answer: full, source: "curated", scriptTitle: script.title});
        }
      }
    }

    // Step 2 — no curated match, generate a full Gemini answer
    const prompt = `${system}\n\nCourse: ${course}\nLevel: ${b.level || "Not specified"}\nStudent question: ${b.question}\n\nProvide a complete, helpful answer following the format above. Do not cut off — finish the full response.`;

    const geminiAnswer = await geminiCall(key, prompt, 2000, 0.35);

    if (!geminiAnswer) {
      return Response.json({error: "Gemini service could not answer right now."}, {status: 502});
    }

    return Response.json({answer: geminiAnswer, source: "gemini"});

  } catch {
    return Response.json({error: "Unable to generate an answer right now."}, {status: 500});
  }
}
