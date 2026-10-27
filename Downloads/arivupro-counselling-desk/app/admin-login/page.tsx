'use client';
import {useState} from 'react';
import {useRouter,useSearchParams} from 'next/navigation';
import {Suspense} from 'react';

function LoginForm(){
  const [password,setPassword]=useState('');
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(false);
  const router=useRouter();
  const params=useSearchParams();
  const returnTo=params.get('return_to')||'/admin';

  async function handleSubmit(e:React.FormEvent){
    e.preventDefault();
    setLoading(true);setError('');
    const res=await fetch('/api/admin-login',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password}),
    });
    if(res.ok){
      router.push(returnTo);
    } else {
      setError('Incorrect password');
      setLoading(false);
    }
  }

  return(
    <main style={{minHeight:'100vh',display:'flex',alignItems:'center',justifyContent:'center',background:'#f0f4f1'}}>
      <div style={{background:'#fff',padding:'40px',borderRadius:'12px',boxShadow:'0 2px 16px rgba(0,0,0,0.1)',width:'100%',maxWidth:'380px'}}>
        <div style={{textAlign:'center',marginBottom:'28px'}}>
          <div style={{fontSize:'28px',fontWeight:'700',color:'#2e8857'}}>ArivuPro</div>
          <div style={{color:'#666',marginTop:'6px'}}>Admin Dashboard Login</div>
        </div>
        <form onSubmit={handleSubmit}>
          <input
            type="password"
            value={password}
            onChange={e=>setPassword(e.target.value)}
            placeholder="Enter admin password"
            required
            style={{width:'100%',padding:'12px',border:'1px solid #ddd',borderRadius:'8px',fontSize:'15px',boxSizing:'border-box',outline:'none'}}
          />
          {error&&<div style={{color:'#e53e3e',marginTop:'8px',fontSize:'14px'}}>{error}</div>}
          <button
            type="submit"
            disabled={loading}
            style={{width:'100%',marginTop:'16px',padding:'12px',background:'#2e8857',color:'#fff',border:'none',borderRadius:'8px',fontSize:'15px',fontWeight:'600',cursor:'pointer'}}
          >
            {loading?'Signing in…':'Sign in'}
          </button>
        </form>
      </div>
    </main>
  );
}

export default function AdminLoginPage(){
  return <Suspense><LoginForm/></Suspense>;
}
