'use client';
import {useRef,useState,useEffect} from 'react';
import {ArrowRight,Check,ShieldCheck,CalendarDays,Loader2,User,Phone,Mail,BookOpen,HelpCircle,Sparkles,Video,Globe} from 'lucide-react';
import {courses} from '@/lib/courses';

const CALENDLY_BASE=process.env.NEXT_PUBLIC_CALENDLY_URL||'https://calendly.com/tech-arivupro/30min';

const DOMAIN_TYPOS:Record<string,string>={
  'gail.com':'gmail.com','gmial.com':'gmail.com','gamil.com':'gmail.com',
  'gmail.co':'gmail.com','gmal.com':'gmail.com','gmali.com':'gmail.com',
  'gnail.com':'gmail.com','gmall.com':'gmail.com','gmail.con':'gmail.com',
  'gmila.com':'gmail.com','gimail.com':'gmail.com','gmaill.com':'gmail.com',
  'gmail.cpm':'gmail.com','gmail.ocm':'gmail.com','gmail.cm':'gmail.com',
  'gemail.com':'gmail.com','gmai.com':'gmail.com','gmailcom':'gmail.com',
  'yaho.com':'yahoo.com','yahooo.com':'yahoo.com','yahoo.co':'yahoo.com',
  'yahoo.con':'yahoo.com','yhoo.com':'yahoo.com',
  'hotmial.com':'hotmail.com','hotmal.com':'hotmail.com','hotmail.co':'hotmail.com',
  'hotmaill.com':'hotmail.com','hotmail.con':'hotmail.com',
  'outlok.com':'outlook.com','outloook.com':'outlook.com','outlook.con':'outlook.com',
  'redifmail.com':'rediffmail.com','rediffmal.com':'rediffmail.com',
};

function validateEmail(v:string):string{
  const val=v.trim().toLowerCase();
  if(!val)return 'Email address is required.';
  if(!/^[^\s@]+@[^\s@]+\.[a-z]{2,}$/.test(val))return 'Enter a valid email (e.g. you@gmail.com).';
  if((val.match(/@/g)||[]).length!==1)return 'Email must have exactly one @.';
  const [local,domain]=val.split('@');
  if(!local)return 'Enter the part before @.';
  if(local.startsWith('.')||local.endsWith('.'))return 'Email cannot start or end with a dot.';
  if(!domain||!domain.includes('.'))return 'Email domain looks incomplete.';
  const parts=domain.split('.');
  if(parts[parts.length-1].length<2)return 'Email extension is too short.';
  const fix=DOMAIN_TYPOS[domain];
  if(fix)return `Did you mean ${local}@${fix}?`;
  return '';
}

function validatePhone(v:string):string{
  const d=v.replace(/[\s()\-+]/g,'');
  if(!d)return 'Mobile number is required.';
  if(!/^\d+$/.test(d))return 'Only digits allowed.';
  if(d.length!==10)return 'Enter a valid 10-digit mobile number.';
  return '';
}

function buildCalendlyUrl(name:string,email:string,phone:string,course:string,level:string,concern:string):string{
  // a1 = phone, a2 = short course context (shown in calendar invite — keep clean)
  const shortContext=`${course} (${level})`;
  const params=new URLSearchParams({
    name,email,
    a1:phone,
    a2:shortContext,
    // Pass full concern separately but don't surface it in the invite title
    a3:concern.slice(0,300),
    hide_gdpr_banner:'1',
    primary_color:'2e8857',
    background_color:'ffffff',
    text_color:'243d33',
  });
  return `${CALENDLY_BASE}?${params.toString()}`;
}

type Stage='form'|'calendly'|'done';

export default function StudentPage(){
  const [stage,setStage]=useState<Stage>('form');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [emailErr,setEmailErr]=useState('');
  const [phoneErr,setPhoneErr]=useState('');
  const [calendlyUrl,setCalendlyUrl]=useState('');
  const [savedEmail,setSavedEmail]=useState('');
  const [savedId,setSavedId]=useState('');
  const [formValues,setFormValues]=useState({name:'',email:'',phone:'',course:'CA',level:'',concern:''});
  const [charCount,setCharCount]=useState(0);
  const [mounted,setMounted]=useState(false);
  const [doneStep,setDoneStep]=useState(0);
  const [showPopup,setShowPopup]=useState(false);
  const uid=useRef('');

  useEffect(()=>{setTimeout(()=>setMounted(true),80);},[]);

  // Listen for Calendly booking completion event
  useEffect(()=>{
    function onMsg(e:MessageEvent){
      if(e.data?.event==='calendly.event_scheduled'){
        setShowPopup(true);
      }
    }
    window.addEventListener('message',onMsg);
    return()=>window.removeEventListener('message',onMsg);
  },[]);

  function goTo(next:Stage){
    setStage(next);
    window.scrollTo({top:0,behavior:'smooth'});
    if(next==='done'){
      setDoneStep(0);
      setTimeout(()=>setDoneStep(1),400);
      setTimeout(()=>setDoneStep(2),900);
      setTimeout(()=>setDoneStep(3),1400);
    }
  }

  async function handleFormSubmit(e:React.FormEvent<HTMLFormElement>){
    e.preventDefault();setError('');
    const f=new FormData(e.currentTarget);
    const name=String(f.get('name')||'').trim();
    const email=String(f.get('email')||'').trim();
    const phone=String(f.get('phone')||'').trim();
    const course=String(f.get('course')||'');
    const level=String(f.get('level')||'').trim();
    const concern=String(f.get('concern')||'').trim();
    const eErr=validateEmail(email);
    const pErr=validatePhone(phone);
    setEmailErr(eErr);setPhoneErr(pErr);
    if(eErr||pErr)return;
    if(!level){setError('Please enter your current education level.');return;}
    if(concern.length<10){setError('Please describe your question (at least 10 characters).');return;}
    setBusy(true);
    try{
      if(!uid.current){
        const bytes=crypto.getRandomValues(new Uint8Array(16));
        bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
        const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
        uid.current=[hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
      }
      fetch('/api/requests',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({id:uid.current,name,email,phone,course,level,concern,consent:true,wantsCall:true,otpVerified:false,slot:'',website:''}),
      }).catch(()=>{});
      setFormValues({name,email,phone,course,level,concern});
      setSavedEmail(email);setSavedId(uid.current);
      setCalendlyUrl(buildCalendlyUrl(name,email,phone,course,level,concern));
      goTo('calendly');
    }catch(err){setError((err as Error).message);}
    finally{setBusy(false);}
  }

  return(
    <div className={`publicsite pg${mounted?' pg-in':''}`}>
      {/* ── HEADER ── */}
      <header>
        <a href="/" style={{display:'flex',alignItems:'center'}}>
          <img src="/arivupro-horizontal.png" alt="ArivuPro Academy" style={{height:'44px',width:'auto'}}/>
        </a>
      </header>

      <main>

        {/* ══ FORM STAGE ══ */}
        {stage==='form'&&(
          <div className="pg-stage-wrap">
            {/* Floating background orbs */}
            <div className="pg-orbs" aria-hidden>
              <div className="pg-orb pg-orb1"/>
              <div className="pg-orb pg-orb2"/>
              <div className="pg-orb pg-orb3"/>
            </div>

            {/* Floating stat cards */}
            <div className="pg-floats" aria-hidden>
              <div className="pg-float pg-float1">
                <span className="pg-float-num">2,400+</span>
                <span className="pg-float-lbl">Students counselled</span>
              </div>
              <div className="pg-float pg-float2">
                <span className="pg-float-num">4.9 ★</span>
                <span className="pg-float-lbl">Session rating</span>
              </div>
              <div className="pg-float pg-float3">
                <span className="pg-float-num">30 min</span>
                <span className="pg-float-lbl">Free, no pressure</span>
              </div>
            </div>

            {/* Hero */}
            <div className="pg-hero">
              <div className="pg-badge"><Sparkles size={12}/>Free · No commitment · 30 minutes</div>
              <h1 className="pg-title">Talk to a counsellor.<br/><span className="pg-green">Get real clarity.</span></h1>
              <p className="pg-sub">Tell us what you're exploring — CA, CMA, ACCA or more. We'll prepare before the call so every minute counts.</p>
              <div className="pg-trust">
                <span><Check size={11}/>AI-prepared counsellors</span>
                <span><Check size={11}/>Details pre-filled in calendar</span>
                <span><CalendarDays size={11}/>Mon–Sat, 9 AM–7 PM IST</span>
              </div>
            </div>

            {/* Form + aside */}
            <div className="pg-cols">

              {/* Form card */}
              <div className="pg-form-card">
                {error&&<div className="pg-error">{error}</div>}
                <form onSubmit={handleFormSubmit} autoComplete="on">

                  {/* Section: contact */}
                  <div className="pg-sh"><User size={14}/><span>Your contact details</span></div>
                  <div className="pg-row2">
                    <div className="pg-field">
                      <label className="pg-label">Full name <span className="req">*</span></label>
                      <input className="pg-input" name="name" required minLength={2} maxLength={100} autoComplete="name" placeholder="Your full name"/>
                    </div>
                    <div className="pg-field">
                      <label className="pg-label">Mobile number <span className="req">*</span></label>
                      <div className="pg-phone">
                        <span className="pg-phonepre">+91</span>
                        <input className="pg-phoneinput" name="phone" required type="tel" autoComplete="tel" placeholder="98765 43210"
                          onChange={e=>setPhoneErr(validatePhone(e.target.value))}
                          onBlur={e=>setPhoneErr(validatePhone(e.target.value))}/>
                      </div>
                      {phoneErr&&<span className="pg-ferr">{phoneErr}</span>}
                    </div>
                  </div>
                  <div className="pg-field">
                    <label className="pg-label">Email address <span className="req">*</span></label>
                    <input className="pg-input" name="email" type="email" required autoComplete="email" placeholder="you@gmail.com" maxLength={254}
                      onChange={e=>setEmailErr(validateEmail(e.target.value))}
                      onBlur={e=>setEmailErr(validateEmail(e.target.value))}/>
                    {emailErr&&<span className="pg-ferr">{emailErr}</span>}
                  </div>

                  {/* Section: course */}
                  <div className="pg-sh" style={{marginTop:10}}><BookOpen size={14}/><span>Course &amp; your question</span></div>
                  <div className="pg-row2">
                    <div className="pg-field">
                      <label className="pg-label">Course <span className="req">*</span></label>
                      <select className="pg-input" name="course" required>
                        {courses.map(c=><option key={c}>{c}</option>)}
                      </select>
                    </div>
                    <div className="pg-field">
                      <label className="pg-label">Your current level <span className="req">*</span></label>
                      <input className="pg-input" name="level" required maxLength={100} placeholder="e.g. Class 12, B.Com"/>
                    </div>
                  </div>
                  <div className="pg-field">
                    <div className="pg-label-row">
                      <label className="pg-label"><HelpCircle size={12}/>Your question <span className="req">*</span></label>
                      <span className={`pg-cc${charCount>1800?' pg-cc-near':''}`}>{charCount}/2000</span>
                    </div>
                    <textarea className="pg-textarea" name="concern" required minLength={10} maxLength={2000} rows={5}
                      placeholder="Tell us about your goals, the course you're exploring, or anything you'd like to discuss."
                      onChange={e=>setCharCount(e.target.value.length)}/>
                  </div>

                  <label className="pg-consent">
                    <input type="checkbox" name="consent" required style={{width:14,flexShrink:0,accentColor:'#2e8857',marginTop:2}}/>
                    <span>I agree that ArivuPro Academy may contact me about counselling.</span>
                  </label>

                  <div className="pg-form-foot">
                    <span className="pg-secure"><ShieldCheck size={12}/>Secure &amp; private</span>
                    <button className="pg-btn" type="submit" disabled={busy||!!emailErr||!!phoneErr}>
                      {busy
                        ?<><Loader2 size={15} className="spin"/>Loading calendar…</>
                        :<><CalendarDays size={15}/>Pick your slot<ArrowRight size={14}/></>
                      }
                    </button>
                  </div>
                </form>
              </div>

              {/* Aside */}
              <div className="pg-aside">
                <div className="pg-aside-dark">
                  <div className="pg-aside-tag">FREE 30-MIN SESSION</div>
                  <h2 style={{fontSize:22,lineHeight:1.4,margin:'14px 0 10px',fontFamily:'Manrope,sans-serif',color:'#fff',fontWeight:600}}>The right course<br/>changes everything.</h2>
                  <p style={{fontSize:12,lineHeight:1.9,color:'#8db89e',margin:'0 0 18px'}}>Our counsellors study your question before the session so you get answers, not vague advice.</p>
                  <div className="pg-aside-benefit"><Check size={13}/>Course &amp; career path clarity</div>
                  <div className="pg-aside-benefit"><Check size={13}/>Upcoming batch dates &amp; fees</div>
                  <div className="pg-aside-benefit"><Check size={13}/>Eligibility &amp; exam guidance</div>
                </div>
                <div className="pg-aside-steps">
                  <h3 style={{fontSize:13,fontWeight:700,margin:'0 0 16px',fontFamily:'Manrope,sans-serif'}}>How it works</h3>
                  <div className="pg-step"><span className="pg-step-num">01</span><div><strong>Fill your details</strong><p>Takes under 2 minutes.</p></div></div>
                  <div className="pg-step"><span className="pg-step-num">02</span><div><strong>Pick a time slot</strong><p>Calendar opens right after — your info is pre-filled.</p></div></div>
                  <div className="pg-step"><span className="pg-step-num">03</span><div><strong>Get your Meet link</strong><p>We email it before the session.</p></div></div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ══ CALENDLY STAGE ══ */}
        {stage==='calendly'&&(
          <div className="calstage">
            <div className="calwhobanner">
              <div className="calwhoinner">
                <div className="calwhoavatar">{formValues.name[0]||'?'}</div>
                <div className="calwhoinfo">
                  <strong>Booking for {formValues.name}</strong>
                  <span><Mail size={11}/>{formValues.email}&nbsp;·&nbsp;<Phone size={11}/>+91 {formValues.phone}&nbsp;·&nbsp;<BookOpen size={11}/>{formValues.course}</span>
                </div>
                <button className="calwhoedit" onClick={()=>goTo('form')}>Edit ✎</button>
              </div>
            </div>
            {/* Hint bar with visible button */}
            <div className="pg-calhint">
              <CalendarDays size={13}/>
              <span>Choose a date and time below, then click <strong>Schedule Event</strong> — a confirmation will pop up automatically.</span>
            </div>
            {/* "Scheduled?" popup — appears after 8s */}
            {showPopup&&(
              <div className="pg-popup-overlay" onClick={()=>setShowPopup(false)}>
                <div className="pg-popup" onClick={e=>e.stopPropagation()}>
                  <div className="pg-popup-icon"><Check size={28} strokeWidth={3}/></div>
                  <h3>Done scheduling?</h3>
                  <p>Once you&apos;ve picked a slot in the calendar, tap the button below to confirm.</p>
                  <button className="pg-btn" style={{width:'100%',justifyContent:'center'}} onClick={()=>{setShowPopup(false);goTo('done');}}>
                    <Check size={15}/>I&apos;ve scheduled my session
                  </button>
                  <button className="pg-popup-dismiss" onClick={()=>setShowPopup(false)}>Not yet, go back</button>
                </div>
              </div>
            )}

            <div className="calfullbleed">
              <iframe src={calendlyUrl} title="Book a counselling session" allowFullScreen/>
            </div>
            <div className="calbackrow">
              <button className="textbtn" onClick={()=>goTo('form')}>← Go back</button>
            </div>
          </div>
        )}

        {/* ══ DONE STAGE ══ */}
        {stage==='done'&&(
          <div className="pg-done-wrap">
            {/* Confetti */}
            <div className="pg-confetti" aria-hidden>
              {[...Array(20)].map((_,i)=>(
                <div key={i} className="pg-cp" style={{
                  left:`${(i*37+13)%97}%`,
                  background:['#2e8857','#4cd882','#f0d98b','#fff','#a8e6c2','#e8c9ff'][i%6],
                  width:`${6+i%4}px`,height:`${6+i%4}px`,
                  animationDelay:`${(i*0.13)%0.8}s`,
                  animationDuration:`${0.7+i%3*0.2}s`,
                }}/>
              ))}
            </div>

            <div className={`pg-done-card${doneStep>=1?' pg-done-in':''}`}>
              {/* Big check icon */}
              <div className="pg-done-icon">
                <Check size={34} strokeWidth={3}/>
              </div>

              <h2 className="pg-done-title">You&apos;re all set!</h2>
              <p className="pg-done-sub">
                Our counsellor will reach out to <strong>{savedEmail}</strong> with your Google Meet link before the session.
              </p>

              {/* Animated steps */}
              <div className="pg-done-steps">
                <div className={`pg-ds${doneStep>=1?' pg-ds-on':''}`}>
                  <div className="pg-ds-icon"><Check size={12}/></div>
                  <span>Details submitted</span>
                </div>
                <div className="pg-ds-line"/>
                <div className={`pg-ds${doneStep>=2?' pg-ds-on':''}`}>
                  <div className="pg-ds-icon"><Check size={12}/></div>
                  <span>Session scheduled</span>
                </div>
                <div className="pg-ds-line"/>
                <div className={`pg-ds${doneStep>=3?' pg-ds-on':''}`}>
                  <div className="pg-ds-icon"><CalendarDays size={12}/></div>
                  <span>Meet link coming</span>
                </div>
              </div>

              {/* Ref box */}
              <div className="pg-ref">
                <div><span>Reference</span><strong>{savedId.slice(0,8).toUpperCase()}</strong></div>
                <div><span>Course</span><strong>{formValues.course}</strong></div>
              </div>

              <p className="pg-done-note">Check your inbox and spam folder for the confirmation email.</p>

              {/* Explore */}
              <div className="pg-explore-head">While you wait, explore ArivuPro</div>
              <div className="pg-explore-grid">
                <a href="https://www.arivupro.com" target="_blank" rel="noreferrer" className="pg-explore-card pg-explore-web">
                  <div className="pg-explore-icon">
                    <img src="/arivupro-logo.png" alt="ArivuPro" style={{width:26,height:26,objectFit:'contain'}}/>
                  </div>
                  <strong>Visit our website</strong>
                  <p>Courses, faculty, batch schedules and more</p>
                  <span className="pg-explore-arr">→</span>
                </a>
                <a href="https://www.youtube.com/@ArivuProAcademy" target="_blank" rel="noreferrer" className="pg-explore-card pg-explore-yt">
                  <div className="pg-explore-icon pg-yt-icon">
                    {/* YouTube SVG logo */}
                    <svg width="24" height="18" viewBox="0 0 24 18" fill="none">
                      <path d="M23.495 2.813a3.015 3.015 0 0 0-2.12-2.136C19.505 0 12 0 12 0S4.495 0 2.625.677A3.015 3.015 0 0 0 .505 2.813C0 4.695 0 8.625 0 8.625s0 3.93.505 5.812a3.015 3.015 0 0 0 2.12 2.136C4.495 17.25 12 17.25 12 17.25s7.505 0 9.375-.677a3.015 3.015 0 0 0 2.12-2.136C24 12.555 24 8.625 24 8.625s0-3.93-.505-5.812Z" fill="#FF0000"/>
                      <path d="M9.545 12.274V4.976l6.273 3.649-6.273 3.649Z" fill="#fff"/>
                    </svg>
                  </div>
                  <strong>YouTube channel</strong>
                  <p>Free lectures, tips &amp; exam strategies</p>
                  <span className="pg-explore-arr">→</span>
                </a>
              </div>

              <div className="pg-done-btns">
                <a href="mailto:marketing@arivupro.com" className="pg-done-contact">Contact us</a>
                <button className="pg-btn" onClick={()=>{goTo('form');uid.current='';setSavedId('');setSavedEmail('');}}>
                  Book another session <ArrowRight size={14}/>
                </button>
              </div>
            </div>
          </div>
        )}

        <footer style={{padding:'30px 0',display:'flex',justifyContent:'space-between',color:'#9ca89d',fontSize:10}}>
          ArivuPro Academy<span style={{color:'#aab3aa'}}>Student counselling · marketing@arivupro.com</span>
        </footer>
      </main>

      <style>{`
        /* Page */
        /* Stage wrapper — needed for absolute-positioned orbs/floats */
        .pg-stage-wrap{position:relative;overflow:visible}

        /* Orbs */
        .pg-orbs{position:absolute;inset:0;overflow:hidden;pointer-events:none;z-index:0}
        .pg-orb{position:absolute;border-radius:50%;filter:blur(90px);pointer-events:none;animation:pgOrb 10s ease-in-out infinite}
        .pg-orb1{width:420px;height:420px;background:radial-gradient(circle,#2e885718,transparent 70%);top:-120px;left:-80px;animation-delay:0s}
        .pg-orb2{width:320px;height:320px;background:radial-gradient(circle,#4cd88212,transparent 70%);top:-80px;right:-60px;animation-delay:4s}
        .pg-orb3{width:240px;height:240px;background:radial-gradient(circle,#2e885510,transparent 70%);top:40px;left:50%;animation-delay:7s}
        @keyframes pgOrb{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-28px) scale(1.06)}}

        /* Floating stat cards */
        .pg-floats{position:absolute;left:0;right:0;top:0;height:120px;pointer-events:none;z-index:1;overflow:hidden}
        .pg-float{position:absolute;background:#fff;border:1px solid #e0e8e1;border-radius:12px;padding:10px 16px;display:flex;flex-direction:column;gap:2px;box-shadow:0 4px 20px rgba(46,136,87,.08);animation:pgFloat 6s ease-in-out infinite}
        .pg-float-num{font-size:15px;font-weight:800;color:#1a3326;font-family:'Manrope',sans-serif;letter-spacing:-.5px}
        .pg-float-lbl{font-size:10px;color:#7a9284;font-weight:500}
        .pg-float1{left:5%;top:18px;animation-delay:0s}
        .pg-float2{right:6%;top:10px;animation-delay:2s}
        .pg-float3{right:18%;top:52px;animation-delay:4s;display:none}
        @keyframes pgFloat{0%,100%{transform:translateY(0px)}50%{transform:translateY(-8px)}}
        @media(max-width:900px){.pg-float1{display:none}.pg-float2{display:none}}

        /* Position hero above floats */
        .pg-hero{position:relative;z-index:2}

        /* Reset globals interference inside our form card */
        .pg-form-card label{display:block;font-size:12px;font-weight:600;color:#4b6052;margin:0 0 7px}
        .pg-form-card input,.pg-form-card select,.pg-form-card textarea{margin-top:0;min-height:unset;font-size:13px;transition:border-color .2s,box-shadow .2s}
        .pg-form-card .pg-label-row label{margin-bottom:0}

        .pg{opacity:0;transition:opacity .5s ease}
        .pg-in{opacity:1}

        /* Hero */
        .pg-hero{text-align:center;padding:48px 0 36px;max-width:640px;margin:0 auto}
        .pg-badge{display:inline-flex;align-items:center;gap:7px;background:#eaf4ed;color:#2e8857;border:1px solid #c8e2cf;border-radius:20px;padding:7px 15px;font-size:12px;font-weight:600;margin-bottom:18px;animation:pgBadge .5s cubic-bezier(.34,1.56,.64,1) both .2s}
        @keyframes pgBadge{from{opacity:0;transform:scale(.8)}to{opacity:1;transform:scale(1)}}
        .pg-title{font-size:46px;line-height:1.18;letter-spacing:-2px;margin:0 0 14px;font-weight:800;font-family:'Manrope',sans-serif;animation:pgUp .6s ease both .3s}
        .pg-green{color:#2e8857;position:relative;display:inline-block}
        .pg-green::after{content:'';position:absolute;left:0;bottom:-3px;width:100%;height:3px;background:linear-gradient(90deg,#2e8857,#4cd882);border-radius:2px;animation:pgLine .6s ease both .9s;transform-origin:left}
        @keyframes pgLine{from{transform:scaleX(0)}to{transform:scaleX(1)}}
        .pg-sub{font-size:15px;color:#5a7a65;line-height:1.8;margin:0 0 22px;animation:pgUp .6s ease both .4s}
        .pg-trust{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;animation:pgUp .6s ease both .5s}
        .pg-trust span{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#4a6957;background:#f4f9f5;border:1px solid #d4e9d8;border-radius:20px;padding:6px 13px}
        @keyframes pgUp{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:translateY(0)}}

        /* Two-column layout */
        .pg-cols{display:grid;grid-template-columns:1fr 290px;gap:24px;align-items:start;animation:pgUp .6s ease both .4s}

        /* Form card */
        .pg-form-card{background:#fff;border:1px solid #e0e8e1;border-radius:16px;padding:28px 28px 24px}

        /* Section header inside form */
        .pg-sh{display:flex;align-items:center;gap:9px;font-size:12px;font-weight:700;color:#2e8857;padding-bottom:10px;border-bottom:1px solid #edf2ed;margin-bottom:16px}
        .pg-sh:not(:first-child){margin-top:6px}

        /* Fields */
        .pg-row2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
        .pg-field{margin-bottom:14px}
        .pg-label{display:block;font-size:12px;font-weight:600;color:#4b6052;margin-bottom:7px;display:flex;align-items:center;gap:5px}
        .pg-label-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px}
        .pg-label-row .pg-label{margin-bottom:0}
        .pg-cc{font-size:10px;color:#a0ad9f;font-weight:400}
        .pg-cc-near{color:#b07f2a}
        .pg-input{display:block;width:100%;padding:11px 12px;border:1.5px solid #dde7dd;border-radius:8px;font-size:13px;color:#243d33;background:#fff;outline:none;transition:border-color .2s,box-shadow .2s;box-sizing:border-box;font-family:inherit}
        .pg-input:focus{border-color:#2e8857;box-shadow:0 0 0 3px #2e885715}
        .pg-input::placeholder{color:#b0bab3}
        .pg-textarea{display:block;width:100%;padding:11px 12px;border:1.5px solid #dde7dd;border-radius:8px;font-size:13px;color:#243d33;background:#fff;outline:none;transition:border-color .2s,box-shadow .2s;box-sizing:border-box;font-family:inherit;resize:vertical;line-height:1.7}
        .pg-textarea:focus{border-color:#2e8857;box-shadow:0 0 0 3px #2e885715}
        .pg-textarea::placeholder{color:#b0bab3}

        /* Phone combo */
        .pg-phone{display:flex;align-items:center;border:1.5px solid #dde7dd;border-radius:8px;overflow:hidden;background:#fff;transition:border-color .2s,box-shadow .2s}
        .pg-phone:focus-within{border-color:#2e8857;box-shadow:0 0 0 3px #2e885715}
        .pg-phonepre{padding:0 10px;font-size:13px;font-weight:600;color:#4a6052;background:#f3f8f4;border-right:1.5px solid #dde7dd;height:42px;display:flex;align-items:center;flex-shrink:0}
        .pg-phoneinput{flex:1;border:none !important;box-shadow:none !important;background:transparent;padding:11px 12px;font-size:13px;color:#243d33;outline:none;font-family:inherit}
        .pg-phoneinput::placeholder{color:#b0bab3}
        .pg-ferr{display:block;color:#c0392b;font-size:11px;margin-top:4px;font-weight:500}

        /* Consent */
        .pg-consent{display:flex;align-items:flex-start;gap:8px;font-size:11px;color:#7d8d81;line-height:1.7;margin:6px 0 18px;cursor:pointer}

        /* Form footer */
        .pg-form-foot{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #edf1ed;padding-top:18px;gap:12px;flex-wrap:wrap}
        .pg-secure{display:flex;align-items:center;gap:5px;font-size:11px;color:#8c9a8e}

        /* Error */
        .pg-error{padding:11px 14px;background:#fef3f2;border:1px solid #fcd4d0;border-radius:8px;font-size:12px;color:#b94040;margin-bottom:16px;line-height:1.6}

        /* Primary button */
        .pg-btn{display:inline-flex;align-items:center;gap:8px;padding:12px 20px;background:linear-gradient(135deg,#2e8857,#1e6b42);color:#fff;border:none;border-radius:9px;font-size:13px;font-weight:700;cursor:pointer;transition:transform .2s,box-shadow .2s;white-space:nowrap;font-family:inherit}
        .pg-btn:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 8px 22px rgba(46,136,87,.35)}
        .pg-btn:active{transform:scale(.97)}
        .pg-btn:disabled{opacity:.55;cursor:wait}
        .pg-btn-sm{padding:9px 15px;font-size:12px}

        /* Aside */
        .pg-aside{display:flex;flex-direction:column;gap:18px;position:static;width:auto;border:none;padding:0;inset:unset}
        .pg-aside-dark{background:linear-gradient(145deg,#1a3d2b,#0f2419);border-radius:14px;padding:24px 20px;color:#fff}
        .pg-aside-tag{font-size:9px;letter-spacing:2px;color:#4cd882;font-weight:700;margin-bottom:10px}
        .pg-aside-benefit{display:flex;align-items:center;gap:8px;font-size:11px;color:#c8e8d0;margin-top:10px}
        .pg-aside-benefit svg{color:#4cd882;flex-shrink:0}
        .pg-aside-steps{background:#fff;border:1px solid #e0e8e1;border-radius:14px;padding:20px}
        .pg-step{display:flex;gap:11px;margin-bottom:16px}
        .pg-step:last-child{margin-bottom:0}
        .pg-step-num{color:#9eb1a1;font-size:11px;flex-shrink:0;padding-top:2px}
        .pg-step strong{font-size:12px;font-weight:700;display:block}
        .pg-step p{font-size:11px;line-height:1.7;color:#8b978e;margin:3px 0 0}

        /* Calendly hint */
        .pg-calhint{display:flex;align-items:center;gap:10px;background:#f0f7f2;border:1px solid #c8e2cf;border-radius:9px;padding:11px 16px;font-size:12px;color:#2e5a40;flex-wrap:wrap;max-width:1150px;margin:0 auto 16px;box-sizing:border-box;padding-left:44px;padding-right:44px}
        .pg-calhint strong{font-weight:700}

        /* Done stage */
        .pg-done-wrap{position:relative;min-height:70vh;display:flex;align-items:flex-start;justify-content:center;padding:32px 0 60px}
        .pg-confetti{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;overflow:hidden}
        .pg-cp{position:absolute;top:-10px;border-radius:2px;animation:pgFall linear both}
        @keyframes pgFall{0%{transform:translateY(-10px) rotate(0deg);opacity:1}100%{transform:translateY(110vh) rotate(720deg);opacity:0}}
        .pg-done-card{position:relative;z-index:1;background:#fff;border:1px solid #e0e8e1;border-radius:20px;padding:40px 36px;max-width:560px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(46,136,87,.12);opacity:0;transform:translateY(24px) scale(.97);transition:opacity .6s ease,transform .6s cubic-bezier(.34,1.2,.64,1)}
        .pg-done-in{opacity:1;transform:translateY(0) scale(1)}
        .pg-done-icon{width:70px;height:70px;background:linear-gradient(135deg,#2e8857,#4cd882);border-radius:50%;display:grid;place-items:center;margin:0 auto 18px;color:#fff;animation:pgIconPop .5s cubic-bezier(.34,1.56,.64,1) both .3s}
        @keyframes pgIconPop{from{transform:scale(0) rotate(-180deg)}to{transform:scale(1) rotate(0)}}
        .pg-done-title{font-size:30px;font-weight:800;letter-spacing:-1px;margin:0 0 10px;font-family:'Manrope',sans-serif;color:#1a3326}
        .pg-done-sub{font-size:13px;color:#5a7a65;line-height:1.8;margin:0 0 24px}

        /* Progress steps */
        .pg-done-steps{display:flex;align-items:center;justify-content:center;margin:0 0 24px}
        .pg-ds{display:flex;flex-direction:column;align-items:center;gap:5px;font-size:11px;color:#9ab0a2;min-width:90px;transition:color .4s}
        .pg-ds-on{color:#2e8857}
        .pg-ds-icon{width:30px;height:30px;border-radius:50%;background:#e8f1e8;display:grid;place-items:center;color:#9ab0a2;transition:background .4s,color .4s,transform .4s}
        .pg-ds-on .pg-ds-icon{background:#2e8857;color:#fff;transform:scale(1.15)}
        .pg-ds-line{flex:1;height:2px;background:#e8ede8;min-width:24px;margin-bottom:22px}

        /* Ref */
        .pg-ref{display:flex;justify-content:center;gap:28px;background:#f5f9f5;border-radius:10px;padding:13px 18px;margin-bottom:14px;font-size:12px}
        .pg-ref div{display:flex;flex-direction:column;gap:3px;text-align:center}
        .pg-ref span{color:#8a9e90;font-size:10px;text-transform:uppercase;letter-spacing:.8px}
        .pg-ref strong{font-size:14px;font-weight:700;color:#1e3d28}
        .pg-done-note{font-size:12px;color:#8a9e90;line-height:1.8;margin:0 0 24px}

        /* Explore */
        .pg-explore-head{font-size:11px;font-weight:700;color:#4b6052;margin-bottom:12px;text-transform:uppercase;letter-spacing:.8px}
        .pg-explore-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:24px}
        .pg-explore-card{display:flex;flex-direction:column;gap:5px;padding:18px;border-radius:13px;text-decoration:none;border:1px solid #e0e8e1;transition:transform .25s,box-shadow .25s;position:relative;overflow:hidden;text-align:left}
        .pg-explore-card:hover{transform:translateY(-3px);box-shadow:0 10px 28px rgba(0,0,0,.09)}
        .pg-explore-web{background:linear-gradient(135deg,#f0f7f2,#e4f1e8);color:#1a3326}
        .pg-explore-yt{background:linear-gradient(135deg,#fff5f5,#ffe8e8);color:#7a1a1a}
        .pg-explore-icon{width:40px;height:40px;border-radius:10px;display:grid;place-items:center;background:rgba(255,255,255,.7);margin-bottom:3px}
        .pg-explore-web .pg-explore-icon{background:rgba(255,255,255,.9)}
        .pg-yt-icon{background:#fff !important;padding:6px}
        .pg-explore-card strong{font-size:12px;font-weight:700}
        .pg-explore-card p{font-size:11px;line-height:1.6;opacity:.65;margin:0}
        .pg-explore-arr{position:absolute;bottom:12px;right:14px;font-size:15px;opacity:.35;transition:opacity .2s,transform .2s}
        .pg-explore-card:hover .pg-explore-arr{opacity:.7;transform:translateX(3px)}

        .pg-done-btns{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
        .pg-done-contact{display:inline-flex;align-items:center;padding:12px 20px;background:#f0f6f2;color:#2e8857;border:1px solid #c8e2cf;border-radius:9px;font-size:13px;font-weight:600;text-decoration:none;transition:background .2s}
        .pg-done-contact:hover{background:#e0f0e6}

        /* Responsive */
        @media(max-width:900px){
          .pg-cols{grid-template-columns:1fr}
          .pg-title{font-size:36px}
          .pg-aside{display:none}
          .pg-done-card{padding:28px 20px}
          .pg-explore-grid{grid-template-columns:1fr}
        }
        /* Popup overlay */
        .pg-popup-overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;animation:pgFadeIn .25s ease both}
        @keyframes pgFadeIn{from{opacity:0}to{opacity:1}}
        .pg-popup{background:#fff;border-radius:20px;padding:36px 32px;max-width:380px;width:100%;text-align:center;box-shadow:0 24px 64px rgba(0,0,0,.18);animation:pgPopup .35s cubic-bezier(.34,1.56,.64,1) both}
        @keyframes pgPopup{from{opacity:0;transform:scale(.85) translateY(20px)}to{opacity:1;transform:scale(1) translateY(0)}}
        .pg-popup-icon{width:64px;height:64px;background:linear-gradient(135deg,#2e8857,#4cd882);border-radius:50%;display:grid;place-items:center;margin:0 auto 16px;color:#fff}
        .pg-popup h3{font-size:20px;font-weight:800;letter-spacing:-.5px;margin:0 0 8px;font-family:'Manrope',sans-serif;color:#1a3326}
        .pg-popup p{font-size:13px;color:#5a7a65;line-height:1.8;margin:0 0 20px}
        .pg-popup-dismiss{display:block;width:100%;background:none;border:none;color:#8a9e90;font-size:12px;margin-top:12px;cursor:pointer;padding:8px;transition:color .2s}
        .pg-popup-dismiss:hover{color:#2e8857}

        @media(max-width:600px){
          .pg-hero{padding:28px 0 22px}
          .pg-title{font-size:30px;letter-spacing:-1.2px}
          .pg-row2{grid-template-columns:1fr}
          .pg-done-steps{flex-wrap:wrap;gap:10px}
          .pg-ds-line{display:none}
          .pg-calhint{flex-direction:column;align-items:flex-start;padding-left:16px;padding-right:16px}
          .pg-calhint .pg-btn{width:100%;justify-content:center}
          .pg-popup{padding:28px 20px}
        }
      `}</style>
    </div>
  );
}
