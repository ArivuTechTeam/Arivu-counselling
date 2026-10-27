'use client';
import {useState,useEffect} from 'react';
import {useRouter,useSearchParams} from 'next/navigation';
import {Suspense} from 'react';

function LoginForm(){
  const [email,setEmail]=useState('');
  const [password,setPassword]=useState('');
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(false);
  const [shake,setShake]=useState(false);
  const [mounted,setMounted]=useState(false);
  const router=useRouter();
  const params=useSearchParams();
  const returnTo=params.get('return_to')||'/admin';

  useEffect(()=>{setMounted(true);},[]);

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
    <main style={{minHeight:'100vh',display:'flex',alignItems:'center',justifyContent:'center',background:'linear-gradient(135deg,#f0f7f2 0%,#e8f3ec 100%)',padding:'20px'}}>
      <div style={{
        background:'#fff',padding:'44px 40px',borderRadius:'16px',
        boxShadow:'0 4px 40px rgba(46,136,87,0.10)',width:'100%',maxWidth:'400px',
        opacity:mounted?1:0,transform:mounted?'translateY(0)':'translateY(20px)',
        transition:'opacity .4s ease, transform .4s ease',
        animation:shake?'shake .5s ease':undefined,
      }}>
        <div style={{textAlign:'center',marginBottom:'32px'}}>
          <div style={{width:'54px',height:'54px',background:'#2e8857',borderRadius:'14px',display:'grid',placeItems:'center',margin:'0 auto 16px',fontSize:'22px',color:'#fff',fontWeight:'800',letterSpacing:'-1px'}}>A</div>
          <div style={{fontSize:'22px',fontWeight:'800',color:'#1a3326',fontFamily:'Manrope,sans-serif',letterSpacing:'-0.5px'}}>ArivuPro Admin</div>
          <div style={{color:'#7a9286',marginTop:'6px',fontSize:'13px'}}>Sign in to the counselling dashboard</div>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{marginBottom:'16px'}}>
            <label style={{display:'block',fontSize:'12px',fontWeight:'600',color:'#4b6052',marginBottom:'6px'}}>Email address</label>
            <input
              type="email"
              value={email}
              onChange={e=>setEmail(e.target.value)}
              placeholder="marketing@arivupro.com"
              required
              autoComplete="email"
              style={{width:'100%',padding:'12px 14px',border:'1.5px solid #dfe7df',borderRadius:'8px',fontSize:'14px',boxSizing:'border-box',outline:'none',transition:'border-color .2s',color:'#243d33'}}
              onFocus={e=>e.target.style.borderColor='#2e8857'}
              onBlur={e=>e.target.style.borderColor='#dfe7df'}
            />
          </div>
          <div style={{marginBottom:'8px'}}>
            <label style={{display:'block',fontSize:'12px',fontWeight:'600',color:'#4b6052',marginBottom:'6px'}}>Password</label>
            <input
              type="password"
              value={password}
              onChange={e=>setPassword(e.target.value)}
              placeholder="Enter admin password"
              required
              autoComplete="current-password"
              style={{width:'100%',padding:'12px 14px',border:'1.5px solid #dfe7df',borderRadius:'8px',fontSize:'14px',boxSizing:'border-box',outline:'none',transition:'border-color .2s',color:'#243d33'}}
              onFocus={e=>e.target.style.borderColor='#2e8857'}
              onBlur={e=>e.target.style.borderColor='#dfe7df'}
            />
          </div>

          {error&&(
            <div style={{color:'#c0392b',background:'#fdf0f0',border:'1px solid #f5c6c6',borderRadius:'7px',padding:'10px 12px',fontSize:'12px',marginBottom:'12px',marginTop:'8px'}}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{width:'100%',marginTop:'16px',padding:'13px',background:loading?'#5aaa7e':'#2e8857',color:'#fff',border:'none',borderRadius:'9px',fontSize:'14px',fontWeight:'700',cursor:loading?'wait':'pointer',transition:'background .2s, transform .1s',letterSpacing:'-0.2px'}}
            onMouseDown={e=>(e.currentTarget.style.transform='scale(0.98)')}
            onMouseUp={e=>(e.currentTarget.style.transform='scale(1)')}
          >
            {loading?'Signing in…':'Sign in →'}
          </button>
        </form>

        <div style={{textAlign:'center',marginTop:'20px',fontSize:'11px',color:'#9aaa9e'}}>
          ArivuPro Counselling Desk · Admin only
        </div>
      </div>

      <style>{`
        @keyframes shake {
          0%,100%{transform:translateX(0)}
          20%{transform:translateX(-8px)}
          40%{transform:translateX(8px)}
          60%{transform:translateX(-5px)}
          80%{transform:translateX(5px)}
        }
      `}</style>
    </main>
  );
}

export default function AdminLoginPage(){
  return <Suspense><LoginForm/></Suspense>;
}
