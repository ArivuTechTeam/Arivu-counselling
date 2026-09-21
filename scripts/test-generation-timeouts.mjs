// Exercise the real frontend API client with a virtual clock, no live server.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';
const require = createRequire(path.resolve('frontend/package.json'));
const ts = require('typescript');
let source = fs.readFileSync('frontend/lib/api.ts', 'utf8')
  .replace('import { createClient } from "@/lib/supabase";', 'const createClient = () => ({ auth: { getSession: async () => ({data:{session:{access_token:"fixture"}}}) } });')
  .replace('import { PUBLIC_ENV } from "@/lib/public-env";', 'const PUBLIC_ENV = {apiBaseUrl:"http://fixture"};')
  .replace('import { safeDashboardNext } from "@/lib/safe-next";', 'const safeDashboardNext = () => "/dashboard";');
const output = path.resolve('.tmp/generation-client-test.mjs');
fs.mkdirSync(path.dirname(output), {recursive:true});
fs.writeFileSync(output, ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText);
let now=0, serial=0;
const timers = new Map();
globalThis.window = {
  setTimeout(fn,delay) { const id=++serial; timers.set(id,{fn,due:now+delay}); return id; },
  clearTimeout(id) { timers.delete(id); },
  dispatchEvent() {},
};
function advance(ms) {
  now+=ms;
  for (const [id,timer] of timers) if(timer.due<=now) { timers.delete(id); timer.fn(); }
}
const api=await import(pathToFileURL(output).href);
const req={document_id:'document',subject_id:'subject',chapter_name:'Maths',selected_topics:[],type_counts:{},cognitive_level:'mixed',difficulty:'medium'};
const ok=data=>new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
for(const generate of [()=>api.generateBlueprintQuiz(req),()=>api.generateFromJob('analysis',req)]) {
  let posts=0;
  globalThis.fetch=async (url,init)=>{
    if(init.method==='GET') return ok({enabled:false,jobs:[]});
    posts++;
    advance(95_000);
    if(init.signal.aborted) throw new DOMException('Aborted','AbortError');
    return ok({quiz_set_id:'saved'});
  };
  assert.equal((await generate()).quiz_set_id,'saved','AI completion after 90s must not be aborted');
  assert.equal(posts,1,'synchronous generation must never be auto-retried');
}
let posts=0;
globalThis.fetch=async (url,init)=>{
  if(init.method==='GET') return ok({enabled:false,jobs:[]});
  posts++; advance(15*60_000+1);
  throw new DOMException('Aborted','AbortError');
};
await assert.rejects(api.generateBlueprintQuiz(req),error=>error.code==='request_timeout' && /server may still finish/.test(error.message));
assert.equal(posts,1);
const bodies=[];
globalThis.fetch=async (url,init)=>{
  if(init.method==='GET') return ok({enabled:true,jobs:[]});
  assert.ok(url.endsWith('/faculty-jobs'),'enabled background processing must not call synchronous generation');
  bodies.push(JSON.parse(init.body));
  if(bodies.length===1) throw new TypeError('Lost acknowledgement');
  return ok({id:'job',status:'queued'});
};
assert.equal((await api.generateBlueprintQuiz(req)).background_job.id,'job');
assert.equal(bodies.length,2);
assert.equal(bodies[0].request_key,bodies[1].request_key,'retry must preserve idempotency key');
assert.equal(timers.size,0);
console.log('PASS: both generation routes survive 90 seconds, true timeout has recovery guidance, no duplicate synchronous POST, background submission retries preserve intent.');
