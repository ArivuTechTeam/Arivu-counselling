export const dynamic='force-dynamic';

export async function GET(){
  const base=process.env.ARIVUPRO_COURSES_API_URL;
  const key=process.env.ARIVUPRO_COURSES_API_KEY;
  if(!base||!key)return Response.json({error:'Env vars not configured.'},{status:503});

  // Use string concat — do NOT use new URL().searchParams (encodes commas in _fields as %2C)
  const separator=base.includes('?')?'&':'?';
  const fetchUrl=`${base}${separator}per_page=100`;

  try{
    const res=await Promise.race([
      fetch(fetchUrl,{headers:{Accept:'application/json','X-API-KEY':key},cache:'no-store'}),
      new Promise<never>((_,reject)=>setTimeout(()=>reject(new Error('timeout')),12000)),
    ]);
    const text=await res.text();
    let data:unknown;
    try{data=JSON.parse(text);}catch{data={raw:text.slice(0,2000)};}
    if(!res.ok)return Response.json({error:`WordPress returned HTTP ${res.status}`,data},{status:502});
    return Response.json({
      count:Array.isArray(data)?(data as unknown[]).length:null,
      fetchUrl,
      data,
    },{headers:{'Cache-Control':'no-store'}});
  }catch(e){
    return Response.json({error:String(e),fetchUrl},{status:502});
  }
}
