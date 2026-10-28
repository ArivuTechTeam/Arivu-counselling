'use client';
import {useRef,useState,useEffect} from 'react';
import {ArrowRight,Check,GraduationCap,ShieldCheck,CalendarDays,Loader2,User,Phone,Mail,BookOpen,HelpCircle,Sparkles} from 'lucide-react';
import {courses} from '@/lib/courses';

const CALENDLY_BASE=process.env.NEXT_PUBLIC_CALENDLY_URL||'https://calendly.com/tech-arivupro/30min';

const DOMAIN_TYPOS:Record<string,string>={
  'gail.com':'gmail.com','gmial.com':'gmail.com','gamil.com':'gmail.com',
  'gmail.co':'gmail.com','gmal.com':'gmail.com','gmali.com':'gmail.com',
  'gnail.com':'gmail.com','gmall.com':'gmail.com','gmail.con':'gmail.com',
  'yaho.com':'yahoo.com','yahooo.com':'yahoo.com','yahoo.co':'yahoo.com',
  'hotmial.com':'hotmail.com','hotmal.com':'hotmail.com','hotmail.co':'hotmail.com',
  'outlok.com':'outlook.com','outloook.com':'outlook.com',
  'redifmail.com':'rediffmail.com','redifmail.in':'rediffmail.com',
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
  if(parts[0].length>2&&!/[aeiou]/.test(parts[0]))return 'Email domain doesn\'t look valid.';
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
  const params=new URLSearchParams({
    name,
    email,
    a1:phone,
    a2:`${course} · ${level} — ${concern}`,
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

  useEffect(()=>{
    if(document.getElementById('arivu-bot-script'))return;
    const s=document.createElement('script');
    s.id='arivu-bot-script';
    s.src='/bot.js';
    s.async=true;
    document.body.appendChild(s);
  },[]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [emailErr,setEmailErr]=useState('');
  const [phoneErr,setPhoneErr]=useState('');
  const [calendlyUrl,setCalendlyUrl]=useState('');
  const [savedEmail,setSavedEmail]=useState('');
  const [savedId,setSavedId]=useState('');
  const [formValues,setFormValues]=useState({name:'',email:'',phone:'',course:'CA',level:'',concern:''});
  const [charCount,setCharCount]=useState(0);
  const id=useRef('');

  function goTo(next:Stage){
    setStage(next);
    window.scrollTo({top:0,behavior:'smooth'});
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
      if(!id.current){
        const bytes=crypto.getRandomValues(new Uint8Array(16));
        bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
        const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
        id.current=[hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
      }
      fetch('/api/requests',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({id:id.current,name,email,phone,course,level,concern,consent:true,wantsCall:true,otpVerified:false,slot:'',website:''}),
      }).catch(()=>{});
      setFormValues({name,email,phone,course,level,concern});
      setSavedEmail(email);setSavedId(id.current);
      setCalendlyUrl(buildCalendlyUrl(name,email,phone,course,level,concern));
      goTo('calendly');
    }catch(err){setError((err as Error).message);}
    finally{setBusy(false);}
  }

  return(
    <div className="publicsite">
      <SiteHeader/>
      <main>

        {/* ── Hero (form stage only) ── */}
        {stage==='form'&&(
          <div className="herosection">
            <div className="herotext">
              <div className="eyebrow">ARIVUPRO ACADEMY · STUDENT COUNSELLING</div>
              <h1>Your questions.<br/><span className="heroaccent">A clearer next step.</span></h1>
              <p className="subtitle">Free 30-min counselling session. Fill in your details once — we carry them into the calendar automatically.</p>
            </div>
            <div className="herobadges">
              <div className="herobadge"><Sparkles size={14}/>AI-assisted counsellors</div>
              <div className="herobadge"><Check size={14}/>Free 30-min session</div>
              <div className="herobadge"><CalendarDays size={14}/>Mon–Sat, 9 AM–7 PM IST</div>
            </div>
          </div>
        )}

        {/* ── Stage: Form ── */}
        {stage==='form'&&(
          <div className="studentgrid">
            <section className="card formcard">
              {error&&<div className="notice" role="alert">{error}</div>}
              <form onSubmit={handleFormSubmit}>
                <div className="fieldsection">
                  <div className="fieldsection-title"><User size={15}/>Contact details</div>
                  <div className="two">
                    <div className="inputwrap">
                      <label>Full name <span className="req">*</span></label>
                      <input name="name" required minLength={2} maxLength={100} autoComplete="name" placeholder="Your full name"/>
                    </div>
                    <div className="inputwrap">
                      <label>Mobile number <span className="req">*</span></label>
                      <div className="phonewrap">
                        <span className="phonepre">+91</span>
                        <input name="phone" required type="tel" autoComplete="tel" placeholder="98765 43210" className="phoneinput"
                          onChange={e=>setPhoneErr(validatePhone(e.target.value))}
                          onBlur={e=>setPhoneErr(validatePhone(e.target.value))}/>
                      </div>
                      {phoneErr&&<span className="fielderror">{phoneErr}</span>}
                    </div>
                  </div>
                  <div className="inputwrap">
                    <label>Email address <span className="req">*</span></label>
                    <input name="email" type="email" required autoComplete="email" placeholder="you@gmail.com" maxLength={254}
                      onChange={e=>setEmailErr(validateEmail(e.target.value))}
                      onBlur={e=>setEmailErr(validateEmail(e.target.value))}/>
                    {emailErr&&<span className="fielderror">{emailErr}</span>}
                  </div>
                </div>

                <div className="fieldsection">
                  <div className="fieldsection-title"><BookOpen size={15}/>Course &amp; question</div>
                  <div className="two">
                    <div className="inputwrap">
                      <label>Course <span className="req">*</span></label>
                      <select name="course" required>{courses.map(c=><option key={c}>{c}</option>)}</select>
                    </div>
                    <div className="inputwrap">
                      <label>Current level <span className="req">*</span></label>
                      <input name="level" required maxLength={100} placeholder="e.g. Class 12, B.Com"/>
                    </div>
                  </div>
                  <div className="inputwrap">
                    <label className="labelflex">
                      <span><HelpCircle size={13}/>Your question <span className="req">*</span></span>
                      <span className={`charcount${charCount>1800?' charnear':''}`}>{charCount}/2000</span>
                    </label>
                    <textarea name="concern" required minLength={10} maxLength={2000} rows={5}
                      placeholder="Tell us about your goals, the course you're exploring, or anything you'd like to discuss."
                      onChange={e=>setCharCount(e.target.value.length)}/>
                  </div>
                </div>

                <label className="consent">
                  <input name="consent" type="checkbox" required/>
                  I agree that ArivuPro Academy may use these details to respond to my query and contact me about counselling.
                </label>

                <div className="formbottom">
                  <span><ShieldCheck size={14}/>Secure &amp; private</span>
                  <button className="primary primarylarge" disabled={busy||!!emailErr||!!phoneErr}>
                    {busy
                      ?<><Loader2 size={16} className="spin"/>Loading calendar…</>
                      :<><CalendarDays size={16}/>Continue to book a slot<ArrowRight size={16}/></>
                    }
                  </button>
                </div>
              </form>
            </section>

            <div className="rightstack">
              <section className="darkcard">
                <span className="tag">LET'S TALK ABOUT YOUR GOALS</span>
                <h2>A good decision<br/>starts with clarity.</h2>
                <p>Share your course interests and concerns. Our counsellors will prepare answers before the session.</p>
                <div className="benefit"><Check size={16}/>Course &amp; study-path guidance</div>
                <div className="benefit"><Check size={16}/>Fees and batch enquiries</div>
                <div className="benefit"><Check size={16}/>Personal session — free, 30 min</div>
              </section>
              <section className="card nextcard">
                <h3>How it works</h3>
                <div className="nextrow"><span>01</span><div><strong>Fill your details</strong><p>Name, email, mobile and your question.</p></div></div>
                <div className="nextrow"><span>02</span><div><strong>Pick a slot in the calendar</strong><p>Your info is pre-filled — just choose a time.</p></div></div>
                <div className="nextrow"><span>03</span><div><strong>Get a Meet link</strong><p>We email a Google Meet link before the session.</p></div></div>
              </section>
            </div>
          </div>
        )}

        {/* ── Stage: Calendly embed ── */}
        {stage==='calendly'&&(
          <div className="calstage">
            {/* Who is booking banner */}
            <div className="calwhobanner">
              <div className="calwhoinner">
                <div className="calwhoavatar">{formValues.name[0]||'?'}</div>
                <div className="calwhoinfo">
                  <strong>Booking for {formValues.name}</strong>
                  <span><Mail size={12}/>{formValues.email}&nbsp;·&nbsp;<Phone size={12}/>+91 {formValues.phone}&nbsp;·&nbsp;<BookOpen size={12}/>{formValues.course}</span>
                </div>
                <button className="calwhoedit" onClick={()=>goTo('form')}>Edit ✎</button>
              </div>
            </div>

            {/* Full-bleed calendar embed */}
            <div className="calfullbleed">
              <iframe
                src={calendlyUrl}
                title="Book a counselling session"
                allowFullScreen
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-top-navigation-by-user-activation"
              />
            </div>

            <div className="calbackrow">
              <button className="textbtn" onClick={()=>goTo('form')}>← Go back and edit details</button>
              <button className="primary primarylarge" onClick={()=>goTo('done')}>
                <Check size={16}/>I've scheduled my session
              </button>
            </div>
          </div>
        )}

        {/* ── Stage: Done ── */}
        {stage==='done'&&(
          <div className="donestage">
            <div className="donecard">
              <div className="doneicon"><Check size={32}/></div>
              <h2>You're all set!</h2>
              <p>A confirmation email is on its way to <strong>{savedEmail}</strong>.</p>
              <div className="donesteps">
                <div className="donestep donestep-done"><Check size={14}/>Details submitted</div>
                <div className="donestepline"/>
                <div className="donestep donestep-done"><Check size={14}/>Session scheduled</div>
                <div className="donestepline"/>
                <div className="donestep donestep-pending"><CalendarDays size={14}/>Meet link coming</div>
              </div>
              <div className="doneinfo">
                <div className="doneinforow"><span>Reference</span><strong>{savedId.slice(0,8).toUpperCase()}</strong></div>
                <div className="doneinforow"><span>Course</span><strong>{formValues.course}</strong></div>
                <div className="doneinforow"><span>Contact</span><strong>{savedEmail}</strong></div>
              </div>
              <p className="donenote">Our counsellor will send a <strong>Google Meet link</strong> to your email before the session. Check your inbox and spam folder.</p>
              <div className="donebtns">
                <a href="mailto:marketing@arivupro.com" className="secondary">Contact us</a>
                <button className="primary" onClick={()=>{goTo('form');id.current='';setSavedId('');setSavedEmail('');}}>
                  Book another session <ArrowRight size={15}/>
                </button>
              </div>
            </div>
          </div>
        )}

        <footer>ArivuPro Academy<span>Student counselling · marketing@arivupro.com</span></footer>
      </main>
    </div>
  );
}

function SiteHeader(){
  return(
    <header>
      <a href="/" style={{display:'flex',alignItems:'center'}}>
        <img src="/arivupro-horizontal.png" alt="ArivuPro Academy" style={{height:'48px',width:'auto'}}/>
      </a>
    </header>
  );
}
