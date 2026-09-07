"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { SplitText } from "@/components/shared/split-text";
import { Brand } from "@/components/ui/brand";
import { initAuthFx } from "@/lib/auth-fx";
import { createClient } from "@/lib/supabase";
import "./login.css";

function MailIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  );
}
function LockIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  );
}

const TICKS = [
  "Bangalore", "Chennai", "Coimbatore", "Live Online",
  "25+ College Tie-ups", "5000+ Daily Learners",
  "1 Lakh+ YouTube Subscribers", "300+ Rank Holders",
];

export default function LoginPage() {
  const router = useRouter();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email || !password) {
      setError("Please enter your email and password.");
      return;
    }
    setLoading(true);
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) {
      setError(error.message);
      return;
    }
    router.push("/dashboard");
  }

  // Floating particle background (ported from the design, no custom cursor).
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    let W = 0, H = 0, mx = -999, my = -999, raf = 0;
    const COLORS = ["rgba(46,136,87,", "rgba(122,229,130,", "rgba(58,160,102,"];
    const resize = () => {
      W = canvas.width = window.innerWidth;
      H = canvas.height = window.innerHeight;
    };
    resize();

    type P = { x: number; y: number; r: number; vx: number; vy: number; color: string; life: number; maxLife: number; opacity: number };
    const make = (): P => ({
      x: Math.random() * W, y: H + 10, r: Math.random() * 2.2 + 0.7,
      vx: (Math.random() - 0.5) * 0.4, vy: -(Math.random() * 0.65 + 0.2),
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      life: Math.random() * 160, maxLife: Math.random() * 210 + 110, opacity: 0,
    });
    const parts: P[] = Array.from({ length: 70 }, make);
    const onMove = (e: MouseEvent) => { mx = e.clientX; my = e.clientY; };
    window.addEventListener("resize", resize);
    window.addEventListener("mousemove", onMove);

    const loop = () => {
      ctx.clearRect(0, 0, W, H);
      for (let i = 0; i < parts.length; i++) {
        for (let j = i + 1; j < parts.length; j++) {
          const dx = parts[i].x - parts[j].x, dy = parts[i].y - parts[j].y;
          const d = Math.hypot(dx, dy);
          if (d < 85) {
            ctx.beginPath();
            ctx.moveTo(parts[i].x, parts[i].y);
            ctx.lineTo(parts[j].x, parts[j].y);
            ctx.strokeStyle = "rgba(46,136,87," + (1 - d / 85) * 0.06 + ")";
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
        const p = parts[i];
        p.life++;
        if (p.life > p.maxLife) {
          Object.assign(p, make());
        } else {
          const fi = 22, fo = 32;
          if (p.life < fi) p.opacity = (p.life / fi) * 0.4;
          else if (p.life > p.maxLife - fo) p.opacity = ((p.maxLife - p.life) / fo) * 0.4;
          else p.opacity = 0.2 + Math.sin(p.life * 0.028) * 0.13;
          const dx = p.x - mx, dy = p.y - my, d = Math.hypot(dx, dy);
          if (d < 115 && d > 0) {
            const f = (115 - d) / 115;
            p.x += (dx / d) * f * 1.7;
            p.y += (dy / d) * f * 1.7;
          }
          p.x += p.vx;
          p.y += p.vy;
        }
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = p.color + p.opacity + ")";
        ctx.fill();
      }
      raf = requestAnimationFrame(loop);
    };
    loop();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMove);
    };
  }, []);

  // ArivuPro entrance animations, custom cursor, magnetic buttons, counters.
  useEffect(() => initAuthFx(), []);

  return (
    <div className="login-page">
      <canvas id="bgCanvas" ref={canvasRef} />
      <div className="wrap">
        {/* LEFT — brand / marketing */}
        <div className="left">
          <div className="apl-ring r1" />
          <div className="apl-ring r2" />
          <div className="apl-ring r3" />
          <div className="apl-ring r4" />
          <div className="blob b1" />
          <div className="blob b2" />
          <div className="left-inner">
            <div className="eyebrow">
              <div className="eline" />
              <span className="etxt">South India&apos;s No.1 Commerce Academy</span>
            </div>
            <h1 className="headline">
              <SplitText text="Shape your " />
              <SplitText text="future" em />
              <br />
              <SplitText text="one exam at a time." />
            </h1>
            <p className="subtext">
              Join 1,00,000+ students who cracked CA, CS, ACCA, CMA, CFA and
              more. Expert faculty. Proven results. 10+ years of excellence.
            </p>

            <div className="stats">
              <div className="stat">
                <span className="stat-icon">🎓</span>
                <div className="stat-num"><span className="counter" data-to="100" data-suffix="K+">0</span></div>
                <div className="stat-lbl">Students Trained</div>
                <div className="stat-bar"><div className="stat-fill" style={{ width: "92%" }} /></div>
              </div>
              <div className="stat">
                <span className="stat-icon">🏆</span>
                <div className="stat-num gold"><span className="counter" data-to="300" data-suffix="+">0</span></div>
                <div className="stat-lbl">National Rank Holders</div>
                <div className="stat-bar"><div className="stat-fill" style={{ width: "75%" }} /></div>
              </div>
              <div className="stat">
                <span className="stat-icon">⭐</span>
                <div className="stat-num"><span className="counter" data-to="4.8" data-suffix="★" data-dec="1">0</span></div>
                <div className="stat-lbl">Google Rating</div>
                <div className="stat-bar"><div className="stat-fill" style={{ width: "96%" }} /></div>
              </div>
              <div className="stat">
                <span className="stat-icon">📺</span>
                <div className="stat-num"><span className="counter" data-to="1" data-suffix="L+">0</span></div>
                <div className="stat-lbl">YouTube Community</div>
                <div className="stat-bar"><div className="stat-fill" style={{ width: "82%" }} /></div>
              </div>
              <div className="stat wide">
                <div className="wide-left">
                  <span className="stat-icon">📚</span>
                  <div className="stat-num"><span className="counter" data-to="16">0</span></div>
                  <div className="stat-lbl">Professional Programs</div>
                </div>
                <div className="badges">
                  {["CA", "CS", "ACCA", "CMA", "CFA", "FRM", "CPA", "EA"].map((b) => (
                    <span className="badge" key={b}>{b}</span>
                  ))}
                </div>
              </div>
            </div>

            <div className="ticker">
              <div className="ticker-track">
                {[...TICKS, ...TICKS].map((t, i) => (
                  <div className="tick" key={i}>
                    <span className="tick-dot" />
                    {t}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT — sign-in card */}
        <div className="right">
          <div className="card">
            <div className="card-head">
              <div className="card-logo">
                <Brand height={36} />
              </div>
              <div className="card-title">Welcome Back</div>
              <div className="card-sub">Sign in to continue</div>
            </div>

            <form className="form-body" onSubmit={handleSignIn}>
              {error && (
                <div className="err-box">
                  <span>⚠</span>
                  <span>{error}</span>
                </div>
              )}

              <div className="field">
                <div className="field-label">
                  Email address <span className="req">*</span>
                </div>
                <div className="field-box">
                  <span className="field-icon"><MailIcon /></span>
                  <input
                    className="field-input"
                    type="email"
                    placeholder="you@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                    required
                  />
                </div>
              </div>

              <div className="field">
                <div className="field-label">
                  Password <span className="req">*</span>
                </div>
                <div className="field-box">
                  <span className="field-icon"><LockIcon /></span>
                  <input
                    className="field-input"
                    type={showPw ? "text" : "password"}
                    placeholder="Enter your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="current-password"
                    required
                  />
                  <button
                    type="button"
                    className="pw-eye"
                    onClick={() => setShowPw((s) => !s)}
                  >
                    {showPw ? "Hide" : "Show"}
                  </button>
                </div>
              </div>

              <div className="forgot-row">
                <span className="forgot-link" style={{ cursor: "default", opacity: 0.7 }}>
                  Forgot password? Contact your admin to reset.
                </span>
              </div>

              <button className="btn-signin" type="submit" disabled={loading}>
                {loading ? "Signing in…" : "Sign In →"}
              </button>

              <div className="divider">
                <div className="div-line" />
                <div className="div-text">New to ArivuPro?</div>
                <div className="div-line" />
              </div>

              <Link className="btn-register" href="/signup">
                <div className="reg-icon">✎</div>
                <div className="reg-text">
                  <div className="reg-title"> New User? Create an account</div>
                  <div className="reg-sub">Free registration · Takes 2 minutes</div>
                </div>
                <div className="reg-arrow">→</div>
              </Link>
            </form>

            <div className="card-foot">
              By signing in you agree to our Terms of Service &amp; Privacy
              Policy
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
