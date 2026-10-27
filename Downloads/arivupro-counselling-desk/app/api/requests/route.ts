import {getChatGPTUser} from '../../chatgpt-auth';
import {getDb} from '@/db';
import {requests} from '@/db/schema';
import {eq,desc} from 'drizzle-orm';
import {courses,statuses} from '@/lib/courses';
import {z} from 'zod';
import {sendEmail,studentConfirmationEmail,adminNotificationEmail} from '@/lib/email';

export const dynamic='force-dynamic';
const reply=(data:unknown,status=200)=>Response.json(data,{status,headers:{'Cache-Control':'no-store'}});

async function access(){
  const user=await getChatGPTUser();
  return {user,isStaff:['marketing@arivupro.com','tech@arivupro.com'].includes(user?.email.toLowerCase()||'')};
}

export async function GET(req:Request){
  const {user,isStaff}=await access();
  if(!user)return reply({error:'Please sign in to the admin dashboard.'},401);
  if(!isStaff)return reply({error:'Admin access required.'},403);
  try{
    const rows=await getDb().select().from(requests).orderBy(desc(requests.created)).limit(5000);
    if(new URL(req.url).searchParams.get('format')==='csv'){
      const headers=['Created At','Name','Email','Phone','Course','Level','Slot','Concern','Status','Notes','Meet Link','OTP Verified','Email Sent'];
      const esc=(v:unknown)=>`"${String(v??'').replace(/"/g,'""').replace(/\r?\n/g,' ') }"`;
      const lines=[headers.join(','),...rows.map(r=>[r.created,r.name,r.email,r.phone,r.course,r.level,r.slot,r.concern,r.status,r.notes,r.meetLink,r.otpVerified?'Yes':'No',r.emailSent?'Yes':'No'].map(esc).join(','))];
      return new Response(lines.join('\r\n'),{status:200,headers:{'Content-Type':'text/csv; charset=utf-8','Content-Disposition':'attachment; filename="arivupro-student-requests.csv"','Cache-Control':'no-store'}});
    }
    return reply({rows:rows.slice(0,500),isStaff:true,needsSetup:false});
  }catch{
    return reply({error:'Unable to load enquiries. Please try again.'},503);
  }
}

const submission=z.object({
  id:z.string().uuid(),
  name:z.string().trim().min(2).max(100),
  email:z.string().trim().email().max(254),
  phone:z.string().regex(/^\+?[\d ()-]{7,20}$/,'Enter a valid mobile number'),
  course:z.string().refine(c=>courses.includes(c),'Select a valid course'),
  level:z.string().trim().min(1).max(100),
  concern:z.string().trim().min(10).max(2000),
  consent:z.literal(true),
  wantsCall:z.boolean(),
  otpVerified:z.boolean().optional(),
  slot:z.string().optional(),
  website:z.string().max(0).optional(),
});

function isSameOrigin(req:Request):boolean{
  const origin=req.headers.get('origin');
  if(!origin)return true; // server-to-server, allow
  try{
    const reqHost=new URL(req.url).hostname;
    const originHost=new URL(origin).hostname;
    // Allow same hostname OR localhost (Railway proxies the public hostname)
    return reqHost===originHost||reqHost==='0.0.0.0'||reqHost==='localhost'||originHost===process.env.NEXT_PUBLIC_HOST;
  }catch{return false;}
}

export async function POST(req:Request){
  if(!isSameOrigin(req))return reply({error:'Invalid origin'},403);
  if(Number(req.headers.get('content-length')||0)>16000)return reply({error:'Request too large.'},413);
  try{
    const b=submission.parse(await req.json());

    const adminNote=`Course: ${b.course} (${b.level})\nStudent concern: ${b.concern}\n\nContact:\nEmail: ${b.email}\nPhone: ${b.phone}`;

    await getDb().insert(requests).values({
      id:b.id,
      userId:'public:'+b.id,
      name:b.name,
      email:b.email,
      phone:b.phone,
      course:b.course,
      level:b.level,
      slot:b.slot||'',
      concern:b.concern,
      status:'Requested',
      notes:adminNote,
      meetLink:'',
      otpVerified:b.otpVerified===true,
      emailSent:false,
      created:new Date().toISOString(),
    }).onConflictDoNothing();

    // Send confirmation emails — best-effort, don't fail submission if email errors
    const adminEmail=process.env.ADMIN_EMAIL||'marketing@arivupro.com';
    const studentTpl=studentConfirmationEmail({
      name:b.name,course:b.course,level:b.level,
      slot:b.slot||'',concern:b.concern,referenceId:b.id,
    });
    const adminTpl=adminNotificationEmail({
      studentName:b.name,studentEmail:b.email,studentPhone:b.phone,
      course:b.course,level:b.level,slot:b.slot||'',
      concern:b.concern,referenceId:b.id,
    });

    const [sr,ar]=await Promise.allSettled([
      sendEmail({...studentTpl,to:b.email}),
      sendEmail({...adminTpl,to:adminEmail}),
    ]);

    const emailSent=sr.status==='fulfilled'&&sr.value.ok&&ar.status==='fulfilled'&&ar.value.ok;
    if(emailSent)await getDb().update(requests).set({emailSent:true}).where(eq(requests.id,b.id)).catch(()=>{});

    return reply({ok:true,id:b.id,emailSent});
  }catch(e){
    return reply(
      {error:e instanceof z.ZodError?e.errors[0]?.message||'Please check all fields.':'Unable to save your enquiry. Please try again.'},
      e instanceof z.ZodError?400:503
    );
  }
}

export async function PATCH(req:Request){
  if(!isSameOrigin(req))return reply({error:'Invalid origin'},403);
  const {isStaff}=await access();
  if(!isStaff)return reply({error:'Admin access required.'},403);
  try{
    const b=z.object({
      id:z.string().uuid(),
      status:z.string().refine(s=>statuses.includes(s),'Invalid status'),
      notes:z.string().max(10000),
      meetLink:z.string().url('Enter a valid Meet URL').or(z.literal('')).optional(),
    }).parse(await req.json());

    await getDb().update(requests).set({
      status:b.status,
      notes:b.notes,
      ...(b.meetLink!==undefined?{meetLink:b.meetLink}:{}),
    }).where(eq(requests.id,b.id));

    return reply({ok:true});
  }catch(e){
    return reply({error:e instanceof z.ZodError?e.errors[0]?.message||'Validation error.':'Unable to save changes.'},400);
  }
}
