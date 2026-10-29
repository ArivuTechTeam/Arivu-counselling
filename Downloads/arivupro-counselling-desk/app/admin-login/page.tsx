'use client';
import {useState,useEffect} from 'react';
import {useRouter,useSearchParams} from 'next/navigation';
import {Suspense} from 'react';
import {Eye,EyeOff} from 'lucide-react';

function LoginForm(){
  const [email,setEmail]=useState('');
  const [password,setPassword]=useState('');
  const [showPw,setShowPw]=useState(false);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(false);
  const [shake,setShake]=useState(false);
  const [mounted,setMounted]=useState(false);
  const router=useRouter();
  const params=useSearchParams();
  const returnTo=params.get('return_to')||'/admin';

  useEffect(()=>{setTimeout(()=>setMounted(true),80);},[]);

  async function handleSubmit(e:React.FormEvent){
    e.preventDefault();
    setLoading(true);setError('');
    const res=await fetch('/api/admin-login',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email,password}),
    });
    if(res.ok){
      router.push(returnTo);
    } else {
      const data=await res.json().catch(()=>({}));
      setError(data.error||'Incorrect email or password');
      setShake(true);
      setTimeout(()=>setShake(false),600);
      setLoading(false);
    }
  }

  return(
    <main className="login-bg">
      {/* Floating background orbs */}
      <div className="orb orb1"/>
      <div className="orb orb2"/>
      <div className="orb orb3"/>

      <div className={`login-card${mounted?' login-card-in':''}${shake?' login-shake':''}`}>
        {/* Logo */}
        <div className="login-logo-wrap">
          <img src="/arivupro-horizontal.png" alt="ArivuPro Academy" className="login-logo-img" onError={e=>{(e.target as HTMLImageElement).style.display='none';}}/>
          <div className="login-logo-fallback">arivu<span>pro</span></div>
        </div>
        <div className="login-title">Counselling Desk</div>
        <div className="login-sub">Sign in to access the admin workspace</div>

        <form onSubmit={handleSubmit} style={{marginTop:28}}>
          <div className="login-field">
            <label>Email address</label>
            <input
              type="email"
              value={email}
              onChange={e=>setEmail(e.target.value)}
              placeholder="marketing@arivupro.com"
              required
              autoComplete="email"
              className="login-input"
            />
          </div>
          <div className="login-field">
            <label>Password</label>
            <div className="login-pw-wrap">
              <input
                type={showPw?'text':'password'}
                value={password}
                onChange={e=>setPassword(e.target.value)}
                placeholder="Enter your password"
                required
                autoComplete="current-password"
                className="login-input login-pw-input"
              />
              <button type="button" className="login-pw-toggle" onClick={()=>setShowPw(p=>!p)} tabIndex={-1} aria-label={showPw?'Hide password':'Show password'}>
                {showPw?<EyeOff size={16}/>:<Eye size={16}/>}
              </button>
            </div>
          </div>

          {error&&(
            <div className="login-error">{error}</div>
          )}

          <button type="submit" disabled={loading} className={`login-btn${loading?' login-btn-loading':''}`}>
            {loading?<><span className="login-spinner"/>Signing in…</>:'Sign in →'}
          </button>
        </form>

        <div className="login-foot">ArivuPro Academy · Admin access only</div>
      </div>

      <style>{`
        .login-bg{min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#0d2118 0%,#142d1f 50%,#0a1a10 100%);padding:20px;position:relative;overflow:hidden;font-family:'DM Sans',sans-serif}
        .orb{position:absolute;border-radius:50%;filter:blur(80px);pointer-events:none;animation:orbFloat 8s ease-in-out infinite}
        .orb1{width:400px;height:400px;background:radial-gradient(circle,#2e885730,transparent 70%);top:-100px;left:-100px;animation-delay:0s}
        .orb2{width:300px;height:300px;background:radial-gradient(circle,#1a5c3520,transparent 70%);bottom:-80px;right:-80px;animation-delay:3s}
        .orb3{width:200px;height:200px;background:radial-gradient(circle,#4aad7020,transparent 70%);top:50%;left:60%;animation-delay:5s}
        @keyframes orbFloat{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-30px) scale(1.05)}}
        .login-card{background:rgba(255,255,255,0.04);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid rgba(255,255,255,0.10);padding:44px 40px;border-radius:20px;width:100%;max-width:420px;position:relative;z-index:1;opacity:0;transform:translateY(28px) scale(0.97);transition:opacity .5s ease,transform .5s ease}
        .login-card-in{opacity:1;transform:translateY(0) scale(1)}
        .login-shake{animation:shake .5s ease}
        @keyframes shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-8px)}40%{transform:translateX(8px)}60%{transform:translateX(-5px)}80%{transform:translateX(5px)}}
        .login-logo-wrap{display:flex;align-items:center;justify-content:center;margin-bottom:6px;min-height:48px}
        .login-logo-img{height:44px;width:auto;object-fit:contain;filter:brightness(0) invert(1)}
        .login-logo-fallback{font-size:28px;font-weight:800;color:#fff;letter-spacing:-1px;font-family:'Manrope',sans-serif}
        .login-logo-fallback span{color:#4cd882}
        .login-title{text-align:center;font-size:13px;letter-spacing:2px;text-transform:uppercase;color:#4cd882;font-weight:700;margin-top:4px}
        .login-sub{text-align:center;color:rgba(255,255,255,0.45);font-size:12px;margin-top:6px}
        .login-field{margin-bottom:18px}
        .login-field label{display:block;font-size:11px;font-weight:600;color:rgba(255,255,255,0.6);margin-bottom:7px;letter-spacing:.3px}
        .login-input{display:block;width:100%;padding:13px 14px;background:rgba(255,255,255,0.07);border:1.5px solid rgba(255,255,255,0.12);border-radius:10px;font-size:14px;color:#fff;outline:none;transition:border-color .2s,background .2s;box-sizing:border-box}
        .login-input::placeholder{color:rgba(255,255,255,0.25)}
        .login-input:focus{border-color:#2e8857;background:rgba(46,136,87,0.08)}
        .login-pw-wrap{position:relative}
        .login-pw-input{padding-right:44px}
        .login-pw-toggle{position:absolute;right:12px;top:50%;transform:translateY(-50%);background:none;border:none;color:rgba(255,255,255,0.4);cursor:pointer;display:flex;align-items:center;padding:4px;transition:color .2s}
        .login-pw-toggle:hover{color:rgba(255,255,255,0.8)}
        .login-error{color:#ff7b7b;background:rgba(255,80,80,0.1);border:1px solid rgba(255,80,80,0.2);border-radius:8px;padding:10px 12px;font-size:12px;margin-bottom:12px}
        .login-btn{width:100%;margin-top:8px;padding:14px;background:linear-gradient(135deg,#2e8857,#1e6b42);color:#fff;border:none;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer;transition:opacity .2s,transform .15s;display:flex;align-items:center;justify-content:center;gap:8px;letter-spacing:-.2px}
        .login-btn:hover:not(:disabled){transform:translateY(-1px);opacity:.92}
        .login-btn:active{transform:scale(0.98)}
        .login-btn:disabled{opacity:.6;cursor:wait}
        .login-spinner{width:14px;height:14px;border:2px solid rgba(255,255,255,0.3);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;flex-shrink:0}
        @keyframes spin{to{transform:rotate(360deg)}}
        .login-foot{text-align:center;margin-top:24px;font-size:11px;color:rgba(255,255,255,0.2)}
      `}</style>
    </main>
  );
}

export default function AdminLoginPage(){
  return <Suspense><LoginForm/></Suspense>;
}
