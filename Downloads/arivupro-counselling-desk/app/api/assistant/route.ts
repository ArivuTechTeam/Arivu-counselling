import {getChatGPTUser} from "../../chatgpt-auth";
import {findTalkingPoints} from "@/lib/counselling-answers";
export const dynamic="force-dynamic";

const SIMILARITY_THRESHOLD = 2; // minimum keyword matches to use curated answer

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

export async function POST(req:Request){
  const user=await getChatGPTUser();
  if(!user)return Response.json({error:"Sign in to use the counsellor AI."},{status:401});
  if(!["marketing@arivupro.com","tech@arivupro.com"].includes(user.email.toLowerCase()))
    return Response.json({error:"Counsellor access required."},{status:403});

  try{
    const b=await req.json() as {course?:string;level?:string;question?:string};
    if(!b.question?.trim())return Response.json({error:"Enter a student question."},{status:400});

    // Step 1 — check curated scripts first
    const matches=findTalkingPoints(b.question);
    if(matches.length>0&&matches[0]){
      const top=matches[0];
      // Score the top match — if strong enough, use curated answer
      const words=b.question.toLowerCase().replace(/[^a-z0-9 ]/g,' ').split(/\s+/).filter(w=>w.length>2);
      const score=words.filter(w=>top.keywords.split(' ').includes(w)).length;

      if(score>=SIMILARITY_THRESHOLD){
        const course=b.course||"the course you are considering";
        const answer=top.answer.replace(/\{course\}/g,course);
        const followupText=top.followups.map((f,i)=>`${i+1}. ${f}`).join('\n');
        const full=`${answer}\n\n**Follow-up questions to ask the student:**\n${followupText}\n\n**Before sharing:** ${top.verify}`;
        return Response.json({answer:full,source:'curated',scriptTitle:top.title});
      }
    }

    // Step 2 — no curated match, use Gemini
    const key=process.env.GEMINI_API_KEY;
    if(!key)return Response.json({error:"Gemini API key is not configured. Add GEMINI_API_KEY to your .env file."},{status:503});

    const prompt=`${system}\n\nCourse: ${b.course||"Not specified"}\nLevel: ${b.level||"Not specified"}\nStudent question: ${b.question}\n\nProvide a complete, helpful answer following the format above. Do not cut off — finish the full response.`;

    const response=await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${key}`,
      {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          contents:[{parts:[{text:prompt}]}],
          generationConfig:{maxOutputTokens:2000,temperature:0.35}
        })
      }
    );

    if(!response.ok){
      const err=await response.json().catch(()=>({})) as {error?:{message?:string}};
      const status=response.status;
      if(status===429)return Response.json({error:"Gemini API quota exceeded. Check your Google AI Studio usage limits."},{status:503});
      return Response.json({error:err?.error?.message||"Gemini service could not answer right now."},{status:502});
    }

    const data=await response.json() as {candidates?:Array<{content?:{parts?:Array<{text?:string}>}}>};
    const answer=data.candidates?.[0]?.content?.parts?.map(p=>p.text||"").join("")||"No answer returned.";
    return Response.json({answer,source:'gemini'});

  }catch{
    return Response.json({error:"Unable to generate an answer right now."},{status:500});
  }
}
