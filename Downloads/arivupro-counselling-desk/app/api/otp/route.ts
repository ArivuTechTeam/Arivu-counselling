import {getDb} from '@/db';
import {otpStore} from '@/db/schema';
import {eq} from 'drizzle-orm';
import {z} from 'zod';
export const dynamic='force-dynamic';

const reply=(data:unknown,status=200)=>Response.json(data,{status,headers:{'Cache-Control':'no-store'}});

function generateOTP():string{
  return String(Math.floor(100000+Math.random()*900000));
}

// POST /api/otp — send OTP to phone via SMS (stubbed: returns OTP in dev, sends via gateway in prod)
// Body: {phone: string, action: "send" | "verify", code?: string}
export async function POST(req:Request){
  if(req.headers.get('origin')!==new URL(req.url).origin)return reply({error:'Invalid origin'},403);
  try{
    const b=z.object({
      phone:z.string().regex(/^\+?[0-9]{10,15}$/,'Enter a valid 10-digit mobile number'),
      action:z.enum(['send','verify']),
      code:z.string().optional(),
    }).parse(await req.json());

    const db=getDb();
    const normalised=b.phone.replace(/[\s()-]/g,'');

    if(b.action==='send'){
      // Rate-limit: check if an unexpired OTP already exists
      const existing=await db.select().from(otpStore).where(eq(otpStore.phone,normalised)).limit(1);
      if(existing.length>0){
        const exp=new Date(existing[0].expiresAt);
        const secsLeft=Math.floor((exp.getTime()-Date.now())/1000);
        if(secsLeft>0&&existing[0].attempts>=5)
          return reply({error:`Too many attempts. Wait ${secsLeft}s before retrying.`},429);
      }

      const code=generateOTP();
      const expiresAt=new Date(Date.now()+10*60*1000).toISOString();

      await db.insert(otpStore).values({phone:normalised,code,expiresAt,attempts:0})
        .onConflictDoUpdate({target:otpStore.phone,set:{code,expiresAt,attempts:0}});

      // In production: send SMS via Twilio / MSG91 / Fast2SMS
      // For now: return code in response (remove in production!)
      const isDev=process.env.NODE_ENV!=='production';
      return reply({ok:true,message:'OTP sent to your mobile number.',...(isDev?{devOtp:code}:{})});
    }

    if(b.action==='verify'){
      if(!b.code)return reply({error:'Enter the OTP sent to your phone.'},400);
      const row=await db.select().from(otpStore).where(eq(otpStore.phone,normalised)).limit(1);
      if(!row.length)return reply({error:'No OTP found. Request a new one.'},400);

      const {code,expiresAt,attempts}=row[0];
      if(new Date(expiresAt)<new Date())
        return reply({error:'OTP has expired. Request a new one.'},400);
      if(attempts>=5)
        return reply({error:'Too many failed attempts. Request a new OTP.'},429);

      if(b.code!==code){
        await db.update(otpStore).set({attempts:attempts+1}).where(eq(otpStore.phone,normalised));
        return reply({error:`Incorrect OTP. ${4-attempts} attempt(s) remaining.`},400);
      }

      // Verified — delete the record
      await db.delete(otpStore).where(eq(otpStore.phone,normalised));
      return reply({ok:true,verified:true});
    }

    return reply({error:'Unknown action.'},400);
  }catch(e){
    if(e instanceof z.ZodError)return reply({error:e.errors[0]?.message||'Invalid input.'},400);
    return reply({error:'OTP service error. Please try again.'},500);
  }
}
