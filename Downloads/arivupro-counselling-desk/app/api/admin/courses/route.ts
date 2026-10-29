import {getChatGPTUser} from "../../../chatgpt-auth";
export const dynamic='force-dynamic';

// Auth-protected courses proxy — fetched FROM THE BROWSER (user's IP, not Railway's)
// so Cloudflare never blocks it. Returns clean JSON array for the admin assistant.
export async function GET(){
  const user=await getChatGPTUser();
  if(!user)return Response.json({error:'Sign in required.'},{status:401});
  if(!['marketing@arivupro.com','tech@arivupro.com'].includes(user.email.toLowerCase()))
    return Response.json({error:'Admin access required.'},{status:403});

  const base=process.env.ARIVUPRO_COURSES_API_URL;
  const key=process.env.ARIVUPRO_COURSES_API_KEY;
  if(!base||!key)return Response.json({error:'API not configured.'},{status:503});

  const sep=base.includes('?')?'&':'?';
  const url=`${base}${sep}per_page=100`;

  try{
    const res=await Promise.race([
      fetch(url,{
        headers:{
          'Accept':'application/json',
          'X-API-KEY':key,
          'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
          'Accept-Language':'en-US,en;q=0.9',
          'Referer':'https://www.arivupro.com/',
          'Origin':'https://www.arivupro.com',
        },
        cache:'no-store',
      }),
      new Promise<never>((_,rej)=>setTimeout(()=>rej(new Error('timeout')),10000)),
    ]);
    if(!res.ok){
      const raw=await res.text();
      // Cloudflare captcha — signal the client so it can fall back gracefully
      if(raw.includes('sgcaptcha')||raw.includes('captcha'))
        return Response.json({error:'cloudflare_blocked',raw:raw.slice(0,300)},{status:502});
      return Response.json({error:`WordPress ${res.status}`},{status:502});
    }
    const data=await res.json();
    if(!Array.isArray(data))return Response.json({error:'Unexpected response format.'},{status:502});
    return Response.json(data,{headers:{'Cache-Control':'no-store'}});
  }catch(e){
    return Response.json({error:String(e)},{status:502});
  }
}
