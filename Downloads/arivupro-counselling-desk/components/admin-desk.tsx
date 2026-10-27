'use client';
import {useEffect,useState} from 'react';
import {
  ArrowUpRight,CalendarDays,Check,ChevronRight,Clipboard,GraduationCap,
  LayoutDashboard,MessageCircle,Search,ShieldCheck,Sparkles,Users,
  Clock,BookOpen,ArrowRight,Video,Mail,Phone,RefreshCw,ExternalLink,Loader2,
  CheckCircle2,AlertCircle,XCircle,HelpCircle,Send,LogOut,
} from 'lucide-react';
import DirectAnswers from '@/components/direct-answers';
import {courses,statuses} from '@/lib/courses';

type Row={
  id:string;name:string;email:string;phone:string;course:string;level:string;
  slot:string;concern:string;status:string;notes:string;meetLink:string;
  otpVerified:boolean;emailSent:boolean;created:string;
};

const fmtDate=(s:string)=>{
  if(!s)return 'No slot';
  // Try native parse first (ISO strings); if invalid, return the raw string as-is
  const d=new Date(s);
  if(isNaN(d.getTime()))return s; // plain string like "15 Nov 2026 · 10:00 AM"
  return d.toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit'});
};

const fmtDateShort=(s:string)=>{
  if(!s)return '—';
  const d=new Date(s);
  if(isNaN(d.getTime()))return s;
  return d.toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',hour:'numeric',minute:'2-digit'});
};

const statusIcon=(s:string)=>{
  if(s==='Confirmed')return <CheckCircle2 size={13}/>;
  if(s==='Completed')return <Check size={13}/>;
  if(s==='Cancelled')return <XCircle size={13}/>;
  if(s==='Follow-up')return <AlertCircle size={13}/>;
  return <HelpCircle size={13}/>;
};

const statusColor=(s:string)=>{
  if(s==='Confirmed')return 'statusgreen';
  if(s==='Completed')return 'statusblue';
  if(s==='Cancelled')return 'statusred';
  if(s==='Follow-up')return 'statusamber';
  return 'statusgrey';
};

function gmailComposeUrl(to:string,subject:string,body:string):string{
  return `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

export default function AdminDesk({initialRows=[]}:{initialRows?:Row[]}){
  const [view,setView]=useState<'team'|'assistant'>('team');
  const [rows,setRows]=useState<Row[]>(initialRows as Row[]);
  const [loading,setLoading]=useState(false);
  const [message,setMessage]=useState('');
  const [busy,setBusy]=useState(false);
  const [selected,setSelected]=useState<Row|null>(null);
  const [query,setQuery]=useState('');
  const [filter,setFilter]=useState('All');
  const [notes,setNotes]=useState('');
  const [status,setStatus]=useState('Requested');
  const [meetLink,setMeetLink]=useState('');
  const [course,setCourse]=useState('CA');
  const [level,setLevel]=useState('');
  const [question,setQuestion]=useState('');
  const [aiAnswer,setAiAnswer]=useState('');
  const [aiSource,setAiSource]=useState<'curated'|'gemini'|''>('');
  const [aiScriptTitle,setAiScriptTitle]=useState('');
  const [aiBusy,setAiBusy]=useState(false);
  const [copied,setCopied]=useState('');

  async function refresh(){
    setLoading(true);
    try{
      const r=await fetch('/api/requests');
      const d=await r.json() as {error?:string;rows:Row[]};
      if(!r.ok)throw Error(d.error);
      setRows(d.rows||[]);
    }catch(e){setMessage((e as Error).message||'Unable to load requests.');}
    finally{setLoading(false);}
  }

  useEffect(()=>{refresh();},[]);

  function choose(r:Row){
    setSelected(r);setNotes(r.notes);setStatus(r.status);
    setMeetLink(r.meetLink||'');setCourse(r.course);setLevel(r.level);setQuestion(r.concern);
  }

  async function save(){
    if(!selected)return;
    setBusy(true);setMessage('');
    try{
      const r=await fetch('/api/requests',{
        method:'PATCH',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({id:selected.id,status,notes,meetLink}),
      });
      const d=await r.json() as {error?:string};
      if(!r.ok)throw Error(d.error||'Save failed.');
      setMessage('Changes saved.');
      await refresh();
      // Update selected row with latest data
      setSelected(prev=>prev?{...prev,status,notes,meetLink}:null);
    }catch(e){setMessage((e as Error).message);}
    finally{setBusy(false);}
  }

  async function askAI(){
    if(!question.trim())return;
    setAiBusy(true);setAiAnswer('');setAiSource('');setAiScriptTitle('');
    try{
      const r=await fetch('/api/assistant',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({course,level,question}),
      });
      const d=await r.json() as {answer?:string;error?:string;source?:'curated'|'gemini';scriptTitle?:string};
      if(!r.ok)throw Error(d.error||'AI error');
      setAiAnswer(d.answer||'No answer returned.');
      setAiSource(d.source||'gemini');
      setAiScriptTitle(d.scriptTitle||'');
    }catch(e){setAiAnswer((e as Error).message);}
    finally{setAiBusy(false);}
  }

  async function copyText(text:string,label:string){
    try{await navigator.clipboard.writeText(text);setCopied(label);setTimeout(()=>setCopied(''),2000);}
    catch{setCopied('Copy failed — select manually.');}
  }

  const filtered=rows.filter(r=>
    (filter==='All'||r.status===filter)&&
    `${r.name} ${r.course} ${r.concern} ${r.email} ${r.phone}`.toLowerCase().includes(query.toLowerCase())
  );

  const stats=[
    ['Total',rows.length],
    ['Requested',rows.filter(r=>r.status==='Requested').length],
    ['Confirmed',rows.filter(r=>r.status==='Confirmed').length],
    ['Completed',rows.filter(r=>r.status==='Completed').length],
  ];

  return(
    <div className="shell">
      {/* Sidebar */}
      <aside>
        <a className="brand" href="/"><span className="brandmark"><GraduationCap size={25}/></span><span>arivu<span className="brandgreen">pro</span><small>COUNSELLING DESK</small></span></a>
        <div className="navlabel">WORKSPACE</div>
        <button className={view==='team'?'nav active':'nav'} onClick={()=>{setView('team');setMessage('');}}>
          <LayoutDashboard size={19}/>Counsellor workspace
        </button>
        <button className={view==='assistant'?'nav active':'nav'} onClick={()=>{setView('assistant');setMessage('');}}>
          <Sparkles size={19}/>Direct answers &amp; AI
        </button>
        <div className="asidecard">
          <div className="miniicon"><MessageCircle size={20}/></div>
          <strong>Clarity starts with<br/>a conversation.</strong>
          <p>Helping students find their next step, one session at a time.</p>
          <span>ArivuPro Academy <ArrowUpRight size={14}/></span>
        </div>
        <div className="asidefoot">
          <span className="dot"/>Private workspace<small>All times in IST</small>
        </div>
      </aside>

      <div className="body">
        <header>
          <span>ArivuPro <ChevronRight size={14}/> <b>{view==='team'?'Counsellor Workspace':'Answer Assistant'}</b></span>
          <div className="headerend">
            <span className="pill">ArivuPro Academy</span>
            <span className="avatar">AP</span>
            <button
              className="actionbtn"
              style={{fontSize:'11px',gap:'6px'}}
              onClick={async()=>{
                await fetch('/api/admin-login',{method:'DELETE'});
                window.location.href='/admin-login';
              }}
              title="Sign out"
            >
              <LogOut size={13}/>Sign out
            </button>
          </div>
        </header>

        <main>
          {message&&<div role="status" className="notice">{message}<button aria-label="Dismiss" onClick={()=>setMessage('')}>×</button></div>}

          {/* ── Team / Requests view ── */}
          {view==='team'&&(
            <>
              <div className="eyebrow">COUNSELLOR WORKSPACE</div>
              <h1>Good conversations<br/>start here.</h1>
              <p className="subtitle">Review student requests, update statuses, add Google Meet links and prepare answers.</p>

              {/* Stats */}
              <div className="stats">
                {stats.map(([t,n])=>(
                  <div className="card stat" key={String(t)}><span>{t}</span><strong>{n}</strong></div>
                ))}
              </div>

              <div className="teamgrid">
                {/* Request list */}
                <section className="card">
                  <div className="heading">
                    <h2>Student requests</h2>
                    <div style={{display:'flex',gap:'8px'}}>
                      <button className="textbtn" onClick={()=>{window.location.href='/api/requests?format=csv';}} title="Download all student requests as CSV"><ExternalLink size={14}/>Export CSV</button>
                      <button className="textbtn" onClick={refresh} disabled={loading}><RefreshCw size={14}/>{loading?'Loading…':'Refresh'}</button>
                    </div>
                  </div>

                  <div className="toolbar">
                    <label className="search">
                      <Search size={17}/>
                      <input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search name, course, concern…"/>
                    </label>
                    <select value={filter} onChange={e=>setFilter(e.target.value)}>
                      {['All',...statuses].map(x=><option key={x}>{x}</option>)}
                    </select>
                  </div>

                  {loading?<p className="muted">Loading requests…</p>
                  :filtered.length===0?<div className="empty"><Users size={35}/><h3>No requests found</h3><p>{rows.length?'Try a different filter.':'New counselling requests will appear here.'}</p></div>
                  :filtered.map(r=>(
                    <button className={`studentrow${selected?.id===r.id?' selected':''}`} key={r.id} onClick={()=>choose(r)}>
                      <span className="studentavatar">{r.name?.[0]||'?'}</span>
                      <div>
                        <strong>{r.name}</strong>
                        <p>{r.course} · {fmtDateShort(r.slot)}</p>
                        <small>{r.concern}</small>
                      </div>
                      <div style={{display:'flex',flexDirection:'column',alignItems:'flex-end',gap:5}}>
                        <span className={`status ${statusColor(r.status)}`}>{statusIcon(r.status)}{r.status}</span>
                        {r.otpVerified&&<span className="verifiedbadge"><Check size={10}/>OTP</span>}
                        {r.meetLink&&<span className="meetbadge"><Video size={10}/>Meet</span>}
                      </div>
                    </button>
                  ))}
                </section>

                {/* Detail panel */}
                <section className="card">
                  {selected?(
                    <>
                      <span className="eyebrow">SESSION DETAILS</span>
                      <h2>{selected.name}</h2>

                      {/* Contact row */}
                      <div className="contactrow">
                        <a href={`mailto:${selected.email}`} className="contactchip"><Mail size={13}/>{selected.email}</a>
                        <a href={`tel:${selected.phone}`} className="contactchip"><Phone size={13}/>{selected.phone}</a>
                      </div>

                      <div className="concern">
                        <b>{selected.course} · {selected.level}</b>
                        <p>{selected.concern}</p>
                        <small><Clock size={12}/> {fmtDate(selected.slot)} IST</small>
                        {selected.otpVerified&&<small style={{color:'#2e8857'}}><Check size={12}/> Mobile verified</small>}
                      </div>

                      {/* Google Meet link */}
                      <label>Google Meet link
                        <div className="meetrow">
                          <input
                            value={meetLink}
                            onChange={e=>setMeetLink(e.target.value)}
                            placeholder="https://meet.google.com/xxx-xxxx-xxx"
                            type="url"
                          />
                          {meetLink&&(
                            <a href={meetLink} target="_blank" rel="noreferrer" className="meetopen"><ExternalLink size={14}/></a>
                          )}
                        </div>
                      </label>

                      {/* Quick actions */}
                      <div className="actionrow">
                        <a
                          className="actionbtn actionbtn-primary"
                          href={gmailComposeUrl(
                            selected.email,
                            `Your ArivuPro Counselling Session${selected.slot?' — '+selected.slot:''}`,
                            `Hi ${selected.name},\n\nThank you for booking a counselling session with ArivuPro Academy.\n\nHere is your Google Meet link:\n${meetLink||'[Paste your Meet link here — meet.google.com]'}\n\nSession booked: ${selected.slot||'To be confirmed'} IST\n\nPlease join on time. Feel free to bring any questions about ${selected.course}.\n\nLooking forward to speaking with you!\n\nBest regards,\nArivuPro Counselling Team\nmarketing@arivupro.com`
                          )}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <Mail size={14}/>Send Meet link to student
                        </a>
                        <button className="actionbtn" onClick={()=>{setView('assistant');setQuestion(selected.concern);setCourse(selected.course);setLevel(selected.level);}}>
                          <Sparkles size={14}/>Get AI answer
                        </button>
                      </div>

                      <label>Session status
                        <select value={status} onChange={e=>setStatus(e.target.value)}>
                          {statuses.map(x=><option key={x}>{x}</option>)}
                        </select>
                      </label>

                      <label>Counsellor notes &amp; next steps
                        <textarea rows={5} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Record advice, follow-ups and next steps…"/>
                      </label>

                      <button className="primary" disabled={busy} onClick={save}>
                        {busy?<><Loader2 size={14} className="spin"/>Saving…</>:<><Check size={16}/>Save changes</>}
                      </button>
                    </>
                  ):(
                    <div className="empty">
                      <MessageCircle size={35}/>
                      <h3>Select a request</h3>
                      <p>Open a request to see details, add a Meet link, and prepare for the session.</p>
                    </div>
                  )}
                </section>
              </div>
            </>
          )}

          {/* ── Assistant view ── */}
          {view==='assistant'&&(
            <>
              <div className="eyebrow">PROFESSIONAL COMMERCE SME</div>
              <h1>A stronger answer.<br/>A more confident counsellor.</h1>
              <p className="subtitle">Read ready-to-use counselling responses, powered by Gemini AI and curated scripts.</p>

              <div className="assistantgrid">
                <section className="card">
                  <div className="cardtitle">
                    <div className="miniicon"><Sparkles/></div>
                    <div><h2>Student context</h2><p>Fill in the student's details to get a tailored answer.</p></div>
                  </div>

                  <div className="two">
                    <label>Course
                      <select value={course} onChange={e=>setCourse(e.target.value)}>
                        {courses.map(x=><option key={x}>{x}</option>)}
                      </select>
                    </label>
                    <label>Level / learner stage
                      <input value={level} onChange={e=>setLevel(e.target.value)} placeholder="e.g. CA Foundation"/>
                    </label>
                  </div>

                  <label>Student's question
                    <textarea value={question} onChange={e=>setQuestion(e.target.value)} rows={5} placeholder="What does the student want to know?"/>
                  </label>

                  {/* Quick prompts */}
                  <div className="chips" style={{marginBottom:16}}>
                    {['Which course suits my career goals?','Can I study while working?','What are the fees?','Am I eligible to join?'].map(x=>(
                      <button key={x} onClick={()=>setQuestion(x)}>{x}</button>
                    ))}
                  </div>

                  {/* Gemini AI answer */}
                  <button className="primary" onClick={askAI} disabled={aiBusy||!question.trim()}>
                    {aiBusy?<><Loader2 size={15} className="spin"/>Generating…</>:<><Sparkles size={15}/>Generate AI answer</>}
                  </button>

                  {aiAnswer&&(
                    <article className="answercard" style={{marginTop:20}}>
                      <div className="answerheading">
                        {aiSource==='curated'
                          ?<span style={{display:'flex',alignItems:'center',gap:6,color:'#166534'}}><Check size={15}/>CURATED SCRIPT{aiScriptTitle&&<small style={{fontWeight:400,opacity:.7}}>— {aiScriptTitle}</small>}</span>
                          :<span><Sparkles size={15}/>GEMINI AI RESPONSE</span>
                        }
                        <button className="textbtn" onClick={()=>copyText(aiAnswer,'AI answer')}>
                          <Clipboard size={14}/>{copied==='AI answer'?'Copied!':'Copy'}
                        </button>
                      </div>
                      <div className="spokenanswer" style={{whiteSpace:'pre-wrap'}}>
                        {aiAnswer.split('\n').map((line,i)=>{
                          if(line.startsWith('**')&&line.endsWith('**'))
                            return <p key={i} style={{fontWeight:700,marginTop:10,marginBottom:2}}>{line.replace(/\*\*/g,'')}</p>;
                          if(line.startsWith('- ')||line.startsWith('• '))
                            return <p key={i} style={{paddingLeft:14,marginBottom:2}}>{'• '+line.slice(2)}</p>;
                          if(line.trim()==='') return <br key={i}/>;
                          return <p key={i} style={{marginBottom:4}}>{line}</p>;
                        })}
                      </div>
                      <div className="actionrow">
                        <button className="actionbtn" onClick={()=>copyText(aiAnswer,'AI answer')}><Clipboard size={13}/>Copy answer</button>
                      </div>
                    </article>
                  )}

                  {/* Curated scripts */}
                  <DirectAnswers key={course+question} course={course} question={question}/>

                  {/* SME brief */}
                  <div className="connection" style={{marginTop:20}}>
                    <span className="amberdot"/>
                    <div>
                      <b>Need a deeper answer?</b>
                      <p>Use the SME brief to prompt ChatGPT's Professional Commerce SME connector for a full researched response.</p>
                    </div>
                  </div>
                  <button
                    className="secondary"
                    style={{marginTop:8}}
                    disabled={!question.trim()}
                    onClick={()=>{
                      const brief=`@Professional Commerce SME\nCourse: ${course}\nLevel: ${level||'Not specified'}\nQuestion: ${question}\n\nAnswer directly then explain reasoning. Verify changing facts against official sources. Never guarantee jobs, ranks, passes or salaries. End with 2 follow-up questions.`;
                      copyText(brief,'SME brief');
                    }}
                  >
                    <Clipboard size={15}/>{copied==='SME brief'?'Brief copied!':'Copy SME brief'}
                  </button>
                  <a className="textbtn" href="https://chatgpt.com/" target="_blank" rel="noreferrer"><ExternalLink size={13}/>Open ChatGPT ↗</a>
                </section>

                <div>
                  <section className="darkcard">
                    <BookOpen size={27}/>
                    <h2>Built around<br/>academic accuracy.</h2>
                    <p>Use curated scripts for common questions and Gemini AI for complex ones. Verify changing facts before sharing.</p>
                    <div className="benefit"><Check size={16}/>Gemini-powered live answers</div>
                    <div className="benefit"><Check size={16}/>15 curated counselling scripts</div>
                    <div className="benefit"><Check size={16}/>Verification notes on every answer</div>
                  </section>
                  <section className="card nextcard">
                    <h3>Before sharing an answer</h3>
                    <p>Verify changing rules with the qualification body. Confirm fees and batches with the programme owner.</p>
                    <p style={{marginTop:10}}>Send unresolved academic questions to the relevant faculty member.</p>
                    <div className="connection" style={{marginTop:16,padding:'12px 14px'}}>
                      <Send size={14}/>
                      <div><b>Quick email to student</b><p>Select a request from the workspace, then use the Email student button to open a pre-filled Gmail draft.</p></div>
                    </div>
                  </section>
                </div>
              </div>
            </>
          )}

          <footer>ArivuPro Academy <span>A clearer path forward.</span></footer>
        </main>
      </div>
    </div>
  );
}
