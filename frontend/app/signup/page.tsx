"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { SplitText } from "@/components/split-text";
import { Brand } from "@/components/ui/brand";
import { listPublicCourses } from "@/lib/api";
import { initAuthFx } from "@/lib/auth-fx";
import { createClient } from "@/lib/supabase";
import "../login/login.css";

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
function UserIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 4-6 8-6s8 2 8 6" />
    </svg>
  );
}
function BookIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2z" />
      <path d="M19 17H6" />
    </svg>
  );
}

const TICKS = [
  "Bangalore", "Chennai", "Coimbatore", "Live Online",
  "25+ College Tie-ups", "5000+ Daily Learners",
  "1 Lakh+ YouTube Subscribers", "300+ Rank Holders",
];

export default function SignupPage() {
  const router = useRouter();
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [role, setRole] = useState("student");
  const [courseId, setCourseId] = useState("");
  const [courses, setCourses] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const tenantId = process.env.NEXT_PUBLIC_DEFAULT_TENANT_ID;

  useEffect(() => {
    if (tenantId) {
      listPublicCourses(tenantId)
        .then(setCourses)
        .catch(() =>
          setError("Couldn't load courses — please refresh the page."),
        );
    }
  }, [tenantId]);

  async function handleSignup(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (!tenantId) {
      setError("Institution not configured (missing NEXT_PUBLIC_DEFAULT_TENANT_ID).");
      return;
    }
    if (!fullName || !email || !password) {
      setError("Please fill in your name, email and password.");
      return;
    }
    if (!courseId) {
      setError("Please select your course.");
      return;
    }
    setLoading(true);
    const supabase = createClient();
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          tenant_id: tenantId,
          role,
          full_name: fullName,
          course_id: courseId, // -> trigger enrolls the user in this course
        },
      },
    });
    setLoading(false);
    if (error) {
      setError(error.message);
      return;
    }
    if (data.session) {
      router.push("/dashboard");
    } else {
      setNotice("Account created. Check your email to confirm it, then sign in.");
    }
  }

  // Floating particle background (same as the sign-in page).
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let W = 0, H = 0, mx = -999, my = -999, raf = 0;
    const COLORS = ["rgba(46,136,87,", "rgba(122,229,130,", "rgba(58,160,102,"];
    const resize = () => { W = canvas.width = window.innerWidth; H = canvas.height = window.innerHeight; };
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
          const dx = parts[i].x - parts[j].x, dy = parts[i].y - parts[j].y, d = Math.hypot(dx, dy);
          if (d < 85) {
            ctx.beginPath(); ctx.moveTo(parts[i].x, parts[i].y); ctx.lineTo(parts[j].x, parts[j].y);
            ctx.strokeStyle = "rgba(46,136,87," + (1 - d / 85) * 0.06 + ")"; ctx.lineWidth = 0.5; ctx.stroke();
          }
        }
        const p = parts[i]; p.life++;
        if (p.life > p.maxLife) { Object.assign(p, make()); }
        else {
          const fi = 22, fo = 32;
          if (p.life < fi) p.opacity = (p.life / fi) * 0.4;
          else if (p.life > p.maxLife - fo) p.opacity = ((p.maxLife - p.life) / fo) * 0.4;
          else p.opacity = 0.2 + Math.sin(p.life * 0.028) * 0.13;
          const dx = p.x - mx, dy = p.y - my, d = Math.hypot(dx, dy);
          if (d < 115 && d > 0) { const f = (115 - d) / 115; p.x += (dx / d) * f * 1.7; p.y += (dy / d) * f * 1.7; }
          p.x += p.vx; p.y += p.vy;
        }
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fillStyle = p.color + p.opacity + ")"; ctx.fill();
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
              <SplitText text="Start your " />
              <SplitText text="journey" em />
              <br />
              <SplitText text="with ArivuPro today." />
            </h1>
            <p className="subtext">
              Create your account, pick your course, and join 1,00,000+ students
              cracking CA, CS, ACCA, CMA, CFA and more.
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

        {/* RIGHT — signup card */}
        <div className="right">
          <div className="card">
            <div className="card-head">
              <div className="card-logo">
                <Brand height={36} />
              </div>
              <div className="card-title">Create your account</div>
              <div className="card-sub">Enrol &amp; get started</div>
            </div>

            <form className="form-body" onSubmit={handleSignup}>
              {error && <div className="err-box"><span>⚠</span><span>{error}</span></div>}
              {notice && <div className="ok-box"><span>✓</span><span>{notice}</span></div>}

              <div className="field">
                <div className="field-label">Full name <span className="req">*</span></div>
                <div className="field-box">
                  <span className="field-icon"><UserIcon /></span>
                  <input className="field-input" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Your full name" autoComplete="name" required />
                </div>
              </div>

              <div className="field">
                <div className="field-label">Email address <span className="req">*</span></div>
                <div className="field-box">
                  <span className="field-icon"><MailIcon /></span>
                  <input className="field-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@email.com" autoComplete="email" required />
                </div>
              </div>

              <div className="field">
                <div className="field-label">Password <span className="req">*</span></div>
                <div className="field-box">
                  <span className="field-icon"><LockIcon /></span>
                  <input className="field-input" type={showPw ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Create a password" minLength={6} autoComplete="new-password" required />
                  <button type="button" className="pw-eye" onClick={() => setShowPw((s) => !s)}>{showPw ? "Hide" : "Show"}</button>
                </div>
              </div>

              <div className="field">
                <div className="field-label">I am a <span className="req">*</span></div>
                <div className="field-box">
                  <span className="field-icon"><UserIcon /></span>
                  <select className="field-input" value={role} onChange={(e) => setRole(e.target.value)}>
                    <option value="student">Student</option>
                    <option value="teacher">Teacher</option>
                  </select>
                </div>
              </div>

              <div className="field">
                <div className="field-label">Course <span className="req">*</span></div>
                <div className="field-box">
                  <span className="field-icon"><BookIcon /></span>
                  <select className="field-input" value={courseId} onChange={(e) => setCourseId(e.target.value)}>
                    <option value="">Select your course…</option>
                    {courses.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <button className="btn-signin" type="submit" disabled={loading}>
                {loading ? "Creating account…" : "Create account →"}
              </button>
            </form>

            <div className="card-foot">
              Already have an account? <Link href="/login">Sign in</Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
