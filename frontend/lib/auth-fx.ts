import gsap from "gsap";

/**
 * The full ArivuPro auth-page animation set (ported from the original HTML):
 * custom cursor, magnetic buttons, orb parallax, an entrance timeline
 * (headline letters, staggered stats, card fly-in, fields), animated counters,
 * stat-bar growth and badge pops. Returns a cleanup function.
 *
 * All GSAP tweens live inside a gsap.context so cleanup can fully revert them —
 * essential under React Strict Mode's double-invoke (otherwise killed .from()
 * tweens leave elements stuck at opacity 0).
 */
export function initAuthFx(): () => void {
  const cleanups: Array<() => void> = [];
  const q = (sel: string) => Array.from(document.querySelectorAll<HTMLElement>(sel));
  const desktop = window.matchMedia("(min-width: 901px)").matches;

  // ── Custom cursor (desktop only) ──────────────────────────────────────────
  if (desktop) {
    document.body.style.cursor = "none";
    const cur = document.createElement("div");
    cur.className = "apl-cur";
    const ring = document.createElement("div");
    ring.className = "apl-cur-ring";
    document.body.append(cur, ring);
    gsap.set([cur, ring], { xPercent: -50, yPercent: -50 });

    let mx = 0, my = 0, rx = 0, ry = 0;
    const onMove = (e: MouseEvent) => { mx = e.clientX; my = e.clientY; };
    window.addEventListener("mousemove", onMove);
    const tick = () => {
      rx += (mx - rx) * 0.13;
      ry += (my - ry) * 0.13;
      gsap.set(cur, { x: mx, y: my });
      gsap.set(ring, { x: rx, y: ry });
    };
    gsap.ticker.add(tick);

    const enter = () => {
      gsap.to(cur, { width: 5, height: 5, duration: 0.14 });
      gsap.to(ring, { width: 52, height: 52, opacity: 0.8, duration: 0.22 });
    };
    const leave = () => {
      gsap.to(cur, { width: 10, height: 10, duration: 0.14 });
      gsap.to(ring, { width: 38, height: 38, opacity: 0.4, duration: 0.22 });
    };
    const hoverEls = q("a, button, .stat");
    hoverEls.forEach((el) => {
      el.addEventListener("mouseenter", enter);
      el.addEventListener("mouseleave", leave);
    });

    cleanups.push(() => {
      window.removeEventListener("mousemove", onMove);
      gsap.ticker.remove(tick);
      hoverEls.forEach((el) => {
        el.removeEventListener("mouseenter", enter);
        el.removeEventListener("mouseleave", leave);
      });
      cur.remove();
      ring.remove();
      document.body.style.cursor = "";
    });
  }

  // ── Magnetic buttons ──────────────────────────────────────────────────────
  q(".btn-signin, .btn-register").forEach((el) => {
    const move = (e: MouseEvent) => {
      const r = el.getBoundingClientRect();
      gsap.to(el, {
        x: ((e.clientX - (r.left + r.width / 2)) / r.width) * 24,
        y: ((e.clientY - (r.top + r.height / 2)) / r.height) * 24,
        duration: 0.3,
        ease: "power2.out",
      });
    };
    const out = () => gsap.to(el, { x: 0, y: 0, duration: 0.6, ease: "elastic.out(1,0.4)" });
    el.addEventListener("mousemove", move);
    el.addEventListener("mouseleave", out);
    cleanups.push(() => {
      el.removeEventListener("mousemove", move);
      el.removeEventListener("mouseleave", out);
    });
  });

  // ── Entrance + counters (inside a context so we can fully revert) ─────────
  const ctx = gsap.context(() => {
    const tl = gsap.timeline();
    tl.from(".left", { x: -60, opacity: 0, duration: 0.55, ease: "expo.out" }, 0)
      .from(".eyebrow", { opacity: 0, y: 16, duration: 0.3 }, 0.1)
      .from(".apl-char", { y: 42, opacity: 0, rotation: 2, duration: 0.35, stagger: 0.012, ease: "back.out(2)" }, 0.18)
      .from(".subtext", { opacity: 0, y: 18, duration: 0.36 }, 0.34)
      .from(".stat", { opacity: 0, y: 26, scale: 0.93, duration: 0.36, stagger: 0.06, ease: "back.out(2)" }, 0.44)
      .from(".ticker", { opacity: 0, duration: 0.3 }, 0.76)
      .from(".card", { opacity: 0, y: 60, scale: 0.96, duration: 0.6, ease: "expo.out" }, 0.1)
      .from(".card-logo", { opacity: 0, x: -16, duration: 0.32 }, 0.34)
      .from(".card-title, .card-sub", { opacity: 0, y: 10, duration: 0.28, stagger: 0.09 }, 0.42)
      .from(".field", { opacity: 0, x: -16, duration: 0.3, stagger: 0.1 }, 0.56)
      .from(".btn-signin", { opacity: 0, y: 14, duration: 0.36, ease: "back.out(2)" }, 0.74)
      .from(".divider", { opacity: 0, duration: 0.26 }, 0.82)
      .from(".forgot-link, .btn-register", { opacity: 0, y: 14, duration: 0.32, stagger: 0.06 }, 0.86);

    q(".stat-fill").forEach((el) => {
      const w = el.style.width || "0%";
      gsap.fromTo(el, { width: "0%" }, { width: w, duration: 1.1, ease: "power3.out", delay: 0.5 });
    });
    gsap.from(".badge", { opacity: 0, scale: 0.4, rotation: -12, duration: 0.28, stagger: 0.05, ease: "back.out(3)", delay: 0.5 });

    q(".counter").forEach((el) => {
      const to = parseFloat(el.dataset.to || "0");
      const suffix = el.dataset.suffix || "";
      const dec = parseInt(el.dataset.dec || "0", 10);
      const obj = { v: 0 };
      gsap.to(obj, {
        v: to,
        duration: 1.6,
        ease: "power2.out",
        delay: 0.5,
        onUpdate: () => {
          el.textContent = (dec ? obj.v.toFixed(dec) : Math.floor(obj.v)) + suffix;
        },
      });
    });
  });
  cleanups.push(() => ctx.revert());

  return () => cleanups.forEach((fn) => fn());
}
