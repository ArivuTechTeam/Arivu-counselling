import {getChatGPTUser} from "../../chatgpt-auth";
export const dynamic="force-dynamic";

const system=`You are ArivuPro Academy’s Professional Commerce SME counsellor. Answer in clear Indian English for students studying CA, CS, CMA India, US CMA, ACCA, CFA, FRM, EA, CPA, CFP, CIA, Class 11/12 Commerce, B.Com and ArivuPro ONE. Identify course, level, jurisdiction and exam attempt. Give a direct student-ready answer first, then brief reasoning, two follow-up questions and a verification note. Never invent fees, eligibility, dates, exemptions, salaries or guarantees. Mark changing facts as Needs verification and recommend the official body or ArivuPro programme owner. Distinguish CMA India from US CMA.`;

export async function POST(req:Request){
  const user=await getChatGPTUser();
  if(!user)return Response.json({error:"Sign in to use the counsellor AI."},{status:401});
  if(!["marketing@arivupro.com","tech@arivupro.com"].includes(user.email.toLowerCase()))
    return Response.json({error:"Counsellor access required."},{status:403});

  try{
    const b=await req.json() as {course?:string;level?:string;question?:string};
    if(!b.question?.trim())return Response.json({error:"Enter a student question."},{status:400});

    const key=process.env.GEMINI_API_KEY;
    if(!key)return Response.json({error:"Gemini API key is not configured. Add GEMINI_API_KEY to your .env file."},{status:503});

    const prompt=`${system}\n\nCourse: ${b.course||"Not specified"}\nLevel: ${b.level||"Not specified"}\nStudent question: ${b.question}`;

    const response=await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${key}`,
      {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          contents:[{parts:[{text:prompt}]}],
          generationConfig:{maxOutputTokens:700,temperature:0.4}
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
    return Response.json({answer});

  }catch{
    return Response.json({error:"Unable to generate an answer right now."},{status:500});
  }
}
