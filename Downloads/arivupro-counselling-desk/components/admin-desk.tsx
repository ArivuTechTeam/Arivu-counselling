'use client';
import {useEffect,useState,useMemo} from 'react';
import {
  ArrowUpRight,CalendarDays,Check,ChevronRight,Clipboard,GraduationCap,
  LayoutDashboard,MessageCircle,Search,Sparkles,Users,
  Clock,BookOpen,ArrowRight,Video,Mail,Phone,RefreshCw,ExternalLink,Loader2,
  CheckCircle2,AlertCircle,XCircle,HelpCircle,Send,LogOut,
} from 'lucide-react';
import DirectAnswers from '@/components/direct-answers';
import {courses,statuses} from '@/lib/courses';
import {BATCH_DATA} from '@/lib/batch-data';

type Row={
  id:string;name:string;email:string;phone:string;course:string;level:string;
  slot:string;concern:string;status:string;notes:string;meetLink:string;
  otpVerified:boolean;emailSent:boolean;created:string;
};

interface BatchItem {
  id:number;
  title:{rendered:string};
  course_level:string;
  location:string;
  start_date:string;
  day_timing:string;
  exam_attempt:string;
  fee:string;
  status:string;
}

const fmtDate=(s:string)=>{
  if(!s)return 'No slot';
  const d=new Date(s);
  if(isNaN(d.getTime()))return s;
  return d.toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit'});
};

const fmtDateShort=(s:string)=>{
  if(!s)return '—';
  const d=new Date(s);
  if(isNaN(d.getTime()))return s;
  return d.toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',hour:'numeric',minute:'2-digit'});
};

// ── Pipeline stages config ────────────────────────────────────────────────────
const PIPELINE:[string,string,string,string][]=[
  // [value, label, color, bg]
  ['Requested',       'Requested',        '#6b7f72', '#f1f5ee'],
  ['Session Scheduled','Scheduled 📅',    '#1a5cb5', '#e8f0fb'],
  ['Session Done',    'Session Done ✓',   '#2e8857', '#e6f4ec'],
  ['Enrolled',        'Enrolled 🎉',      '#7b3fa0', '#f3e8fc'],
  ['Follow-up',       'Follow-up 🔔',     '#8a6c1a', '#fdf6e3'],
  ['Not Interested',  'Not Interested',   '#7a5c3e', '#fdf0e6'],
  ['Cancelled',       'Cancelled',        '#a03030', '#fce8e8'],
];

const statusIcon=(s:string)=>{
  if(s==='Session Scheduled')return <CheckCircle2 size={13}/>;
  if(s==='Session Done')return <Check size={13}/>;
  if(s==='Enrolled')return <Sparkles size={13}/>;
  if(s==='Cancelled')return <XCircle size={13}/>;
  if(s==='Follow-up')return <AlertCircle size={13}/>;
  if(s==='Not Interested')return <XCircle size={13}/>;
  return <HelpCircle size={13}/>;
};

const statusColor=(s:string)=>{
  const p=PIPELINE.find(x=>x[0]===s);
  if(!p)return 'statusgrey';
  return '';// we'll use inline style instead
};

function StatusBadge({s}:{s:string}){
  const p=PIPELINE.find(x=>x[0]===s)||PIPELINE[0];
  return(
    <span className="status" style={{color:p[2],background:p[3],border:`1px solid ${p[2]}22`,gap:5}}>
      {statusIcon(s)}{p[1]}
    </span>
  );
}

function gmailComposeUrl(to:string,subject:string,body:string):string{
  return `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

// ── Batch helpers ──────────────────────────────────────────────────────────────

const MONTH_MAP:Record<string,number>={
  january:0,february:1,march:2,april:3,may:4,june:5,
  july:6,august:7,september:8,october:9,november:10,december:11,
};

function parseBatchDate(s:string):Date|null{
  if(!s||s==='Purchase Anytime'||s==='Will be updated'||s==='----')return null;
  // Format: DD-Month-YYYY e.g. "14-November-2026"
  const parts=s.split('-');
  if(parts.length!==3)return null;
  const day=parseInt(parts[0],10);
  const month=MONTH_MAP[parts[1].toLowerCase()];
  const year=parseInt(parts[2],10);
  if(isNaN(day)||month===undefined||isNaN(year))return null;
  return new Date(year,month,day);
}

// Cutoff: Nov 1 2026
const UPCOMING_CUTOFF=new Date(2026,10,1);

type BatchStatus='upcoming'|'past'|'recorded';

function getBatchStatus(b:BatchItem):BatchStatus{
  const sd=b.start_date;
  if(!sd||sd==='Purchase Anytime'||sd==='Will be updated'||sd==='----')return 'recorded';
  const d=parseBatchDate(sd);
  if(!d)return 'recorded';
  return d>=UPCOMING_CUTOFF?'upcoming':'past';
}

function detectCourseType(b:BatchItem):string{
  const t=b.title.rendered+' '+b.course_level;
  if(/CA Inter|CA Foundation|CA Final/i.test(t))return 'CA';
  if(/CMA USA/i.test(t))return 'CMA USA';
  if(/CMA India|CMA Foundation|CMA Inter|CMA Final|Tambaram CMA/i.test(t))return 'CMA India';
  if(/ACCA/i.test(t))return 'ACCA';
  if(/CSEET|CS /i.test(t))return 'CS';
  if(/CFA/i.test(t))return 'CFA';
  if(/FRM/i.test(t))return 'FRM';
  if(/\bEA\b/i.test(t))return 'EA';
  return 'Other';
}

function detectLocation(b:BatchItem):string{
  const t=b.title.rendered+' '+b.location;
  if(/Koramangala|Malleshwaram|Bangalore/i.test(t))return 'Bangalore';
  if(/Coimbatore/i.test(t))return 'Coimbatore';
  if(/Hyderabad/i.test(t))return 'Hyderabad';
  if(/Trivandrum/i.test(t))return 'Trivandrum';
  if(/Online|Recorded|Live.?online/i.test(t)||b.start_date==='Purchase Anytime')return 'Online';
  if(/Chennai|Tambaram|Nungambakkam/i.test(t))return 'Chennai';
  return 'Other';
}

const COURSE_TYPE_OPTIONS=['All','CA','CMA India','CMA USA','ACCA','CS','CFA','FRM','EA'];
const LOCATION_OPTIONS=['All','Chennai','Bangalore','Coimbatore','Hyderabad','Online'];

// ── Main component ──────────────────────────────────────────────────────────────

export default function AdminDesk({initialRows=[]}:{initialRows?:Row[]}){
  const [view,setView]=useState<'team'|'assistant'|'batches'>('team');
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

  // Batch filters
  const [batchCourseFilter,setBatchCourseFilter]=useState('All');
  const [batchLocationFilter,setBatchLocationFilter]=useState('All');

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
      setSelected(prev=>prev?{...prev,status,notes,meetLink}:null);
    }catch(e){setMessage((e as Error).message);}
    finally{setBusy(false);}
  }

  async function askAI(){
    if(!question.trim())return;
    setAiBusy(true);setAiAnswer('');setAiSource('');setAiScriptTitle('');
    try{
      let wpData: unknown[]|undefined;
      try{
        const wp=await fetch('/api/admin/courses',{cache:'no-store'});
        if(wp.ok){const d=await wp.json();if(Array.isArray(d))wpData=d;}
      }catch{/* non-fatal */}

      const r=await fetch('/api/assistant',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({course,level,question,...(wpData?{wpData}:{})}),
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
    ['Scheduled',rows.filter(r=>r.status==='Session Scheduled').length],
    ['Enrolled 🎉',rows.filter(r=>r.status==='Enrolled').length],
  ];

  // ── Batch derived data ──
  const batchesWithMeta=useMemo(()=>(BATCH_DATA as BatchItem[]).map(b=>({
    ...b,
    _batchStatus:getBatchStatus(b),
    _courseType:detectCourseType(b),
    _locationGroup:detectLocation(b),
  })),[]);

  const filteredBatches=useMemo(()=>batchesWithMeta.filter(b=>{
    if(batchCourseFilter!=='All'&&b._courseType!==batchCourseFilter)return false;
    if(batchLocationFilter!=='All'&&b._locationGroup!==batchLocationFilter)return false;
    return true;
  }),[batchesWithMeta,batchCourseFilter,batchLocationFilter]);

  const batchStats=useMemo(()=>({
    upcoming:batchesWithMeta.filter(b=>b._batchStatus==='upcoming').length,
    past:batchesWithMeta.filter(b=>b._batchStatus==='past').length,
    recorded:batchesWithMeta.filter(b=>b._batchStatus==='recorded').length,
  }),[batchesWithMeta]);

  return(
    <div className="shell">
      <style>{`
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(14px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes batchPulse {
          0%,100% { box-shadow: 0 0 0 0 rgba(22,163,74,.35); }
          50%      { box-shadow: 0 0 0 5px rgba(22,163,74,0); }
        }
        .batch-table-wrap {
          overflow-x: auto;
          border-radius: 14px;
          border: 1px solid #e5ede8;
        }
        .batch-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }
        .batch-table thead th {
          background: #f4f9f6;
          padding: 11px 14px;
          text-align: left;
          font-weight: 600;
          font-size: 11px;
          letter-spacing: .04em;
          color: #4a7a5c;
          text-transform: uppercase;
          border-bottom: 1px solid #e0ece5;
          white-space: nowrap;
        }
        .batch-table tbody tr {
          border-bottom: 1px solid #eef5f0;
          transition: transform .15s ease, box-shadow .15s ease, background .15s ease;
          animation: fadeInUp .35s ease both;
        }
        .batch-table tbody tr:hover {
          transform: translateY(-2px);
          box-shadow: 0 4px 16px rgba(22,100,50,.08);
          background: #f0faf4 !important;
          position: relative;
          z-index: 1;
        }
        .batch-table td {
          padding: 11px 14px;
          vertical-align: middle;
          color: #1e3a2a;
        }
        .batch-row-upcoming td { background: #f0fdf4; }
        .batch-row-past td { background: #fafafa; color: #8a9e91; }
        .batch-row-recorded td { background: #f5f9ff; }
        .badge-upcoming {
          display:inline-flex;align-items:center;gap:4px;
          background:#dcfce7;color:#15803d;
          font-size:10px;font-weight:700;letter-spacing:.04em;
          padding:3px 8px;border-radius:20px;
          animation: batchPulse 2.2s ease-in-out infinite;
        }
        .badge-past {
          display:inline-flex;align-items:center;gap:4px;
          background:#f1f5f2;color:#6b7b70;
          font-size:10px;font-weight:600;
          padding:3px 8px;border-radius:20px;
        }
        .badge-recorded {
          display:inline-flex;align-items:center;gap:4px;
          background:#dbeafe;color:#1d4ed8;
          font-size:10px;font-weight:700;
          padding:3px 8px;border-radius:20px;
        }
        .batch-stats-bar {
          display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px;
        }
        .batch-stat-chip {
          display:flex;align-items:center;gap:7px;
          padding:8px 16px;border-radius:30px;
          font-size:12px;font-weight:600;
          border:1px solid transparent;
        }
        .batch-stat-chip.upcoming { background:#dcfce7;color:#15803d;border-color:#bbf7d0; }
        .batch-stat-chip.past     { background:#f1f5f2;color:#4a7a5c;border-color:#d1e5d8; }
        .batch-stat-chip.recorded { background:#dbeafe;color:#1d4ed8;border-color:#bfdbfe; }
        .batch-filter-bar {
          display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:18px;
        }
        .batch-filter-bar select {
          padding:7px 12px;border-radius:8px;border:1px solid #d1e5d8;
          background:#fff;font-size:13px;color:#1e3a2a;
          cursor:pointer;transition:border-color .15s;
        }
        .batch-filter-bar select:focus { outline:none;border-color:#22c55e; }
        .batch-filter-label {
          font-size:12px;font-weight:600;color:#4a7a5c;letter-spacing:.04em;text-transform:uppercase;
        }
        .batch-course-name { font-weight:600;color:#1a3328; }
        .batch-location-pill {
          display:inline-block;
          background:#f0fdf4;color:#166534;
          font-size:11px;font-weight:600;
          padding:2px 8px;border-radius:10px;
          border:1px solid #bbf7d0;
        }
      `}</style>

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
        <button className={view==='batches'?'nav active':'nav'} onClick={()=>{setView('batches');setMessage('');}}>
          <CalendarDays size={19}/>Batch schedule
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
          <span>ArivuPro <ChevronRight size={14}/> <b>{view==='team'?'Counsellor Workspace':view==='batches'?'Batch Schedule':'Answer Assistant'}</b></span>
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
                        <StatusBadge s={r.status}/>
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

                      {/* ── Pipeline status picker ── */}
                      <div style={{marginBottom:18}}>
                        <div style={{fontSize:11,fontWeight:600,color:'#4b6052',marginBottom:10}}>Pipeline stage</div>
                        <div style={{display:'flex',flexWrap:'wrap',gap:7}}>
                          {PIPELINE.map(([val,,clr,bg])=>(
                            <button key={val}
                              onClick={()=>setStatus(val)}
                              style={{
                                display:'inline-flex',alignItems:'center',gap:5,
                                padding:'7px 12px',borderRadius:20,
                                fontSize:11,fontWeight:600,cursor:'pointer',
                                border:`1.5px solid ${status===val?clr:clr+'44'}`,
                                background:status===val?clr:bg,
                                color:status===val?'#fff':clr,
                                transform:status===val?'scale(1.05)':'scale(1)',
                                transition:'all .15s',
                                boxShadow:status===val?`0 4px 12px ${clr}40`:'none',
                              }}>
                              {statusIcon(val)}{val}
                            </button>
                          ))}
                        </div>
                      </div>

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

          {/* ── Batch Schedule view ── */}
          {view==='batches'&&(
            <>
              <div className="eyebrow">BATCH SCHEDULE</div>
              <h1>All upcoming batches<br/>at a glance.</h1>
              <p className="subtitle">Live batch schedule across all centres and courses. Filter by course type or location to find the right batch for any student.</p>

              {/* Stats bar */}
              <div className="batch-stats-bar">
                <div className="batch-stat-chip upcoming">
                  <span style={{width:8,height:8,borderRadius:'50%',background:'#16a34a',display:'inline-block'}}/>
                  {batchStats.upcoming} Upcoming
                </div>
                <div className="batch-stat-chip past">
                  <span style={{width:8,height:8,borderRadius:'50%',background:'#9ca3af',display:'inline-block'}}/>
                  {batchStats.past} Already started
                </div>
                <div className="batch-stat-chip recorded">
                  <span style={{width:8,height:8,borderRadius:'50%',background:'#3b82f6',display:'inline-block'}}/>
                  {batchStats.recorded} Recorded / self-paced
                </div>
              </div>

              {/* Filter bar */}
              <div className="batch-filter-bar">
                <span className="batch-filter-label">Course</span>
                <select value={batchCourseFilter} onChange={e=>setBatchCourseFilter(e.target.value)}>
                  {COURSE_TYPE_OPTIONS.map(x=><option key={x}>{x}</option>)}
                </select>
                <span className="batch-filter-label" style={{marginLeft:8}}>Location</span>
                <select value={batchLocationFilter} onChange={e=>setBatchLocationFilter(e.target.value)}>
                  {LOCATION_OPTIONS.map(x=><option key={x}>{x}</option>)}
                </select>
                {(batchCourseFilter!=='All'||batchLocationFilter!=='All')&&(
                  <button
                    className="textbtn"
                    style={{marginLeft:4}}
                    onClick={()=>{setBatchCourseFilter('All');setBatchLocationFilter('All');}}
                  >
                    <XCircle size={13}/>Clear filters
                  </button>
                )}
                <span style={{marginLeft:'auto',fontSize:12,color:'#4a7a5c',fontWeight:600}}>
                  {filteredBatches.length} batch{filteredBatches.length!==1?'es':''} shown
                </span>
              </div>

              {/* Table */}
              <div className="batch-table-wrap">
                <table className="batch-table">
                  <thead>
                    <tr>
                      <th>Course Name</th>
                      <th>Start Date</th>
                      <th>Timing</th>
                      <th>Location</th>
                      <th>Exam Attempt</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredBatches.length===0?(
                      <tr>
                        <td colSpan={6} style={{textAlign:'center',padding:'32px',color:'#8a9e91'}}>
                          No batches match the selected filters.
                        </td>
                      </tr>
                    ):filteredBatches.map((b,idx)=>(
                      <tr
                        key={b.id}
                        className={`batch-row-${b._batchStatus}`}
                        style={{animationDelay:`${Math.min(idx*30,600)}ms`}}
                      >
                        <td>
                          <span className="batch-course-name">{b.title.rendered}</span>
                          <br/>
                          <span style={{fontSize:11,color:'#4a7a5c',opacity:.8}}>{b.course_level}</span>
                        </td>
                        <td style={{whiteSpace:'nowrap'}}>
                          {b.start_date==='Purchase Anytime'||b.start_date==='Will be updated'||b.start_date==='----'
                            ? <span style={{color:'#6b7280',fontStyle:'italic'}}>{b.start_date}</span>
                            : b.start_date
                          }
                        </td>
                        <td style={{fontSize:12,color:'#4a7a5c'}}>{b.day_timing}</td>
                        <td>
                          <span className="batch-location-pill">{b.location}</span>
                        </td>
                        <td style={{fontSize:12}}>{b.exam_attempt}</td>
                        <td>
                          {b._batchStatus==='upcoming'&&(
                            <span className="badge-upcoming">
                              <span style={{width:6,height:6,borderRadius:'50%',background:'#16a34a',display:'inline-block'}}/>
                              Upcoming
                            </span>
                          )}
                          {b._batchStatus==='past'&&(
                            <span className="badge-past">Already Started</span>
                          )}
                          {b._batchStatus==='recorded'&&(
                            <span className="badge-recorded">Anytime</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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

                  <div className="chips" style={{marginBottom:16}}>
                    {['Which course suits my career goals?','Can I study while working?','What are the fees?','Am I eligible to join?'].map(x=>(
                      <button key={x} onClick={()=>setQuestion(x)}>{x}</button>
                    ))}
                  </div>

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

                  <DirectAnswers key={course+question} course={course} question={question}/>

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
