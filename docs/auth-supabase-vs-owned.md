# Authentication Decision Document — Supabase Auth vs Owning Our Auth
**Project:** ArivuPro Quiz Platform (FastAPI backend · Next.js frontend · PostgreSQL)
**Purpose:** A neutral, senior-engineer analysis to settle a team discussion —
*"Should we keep Supabase Auth, or own our authentication (teammate suggests Django)?"*
**Date:** 2026-09-05 · **Stance:** Unbiased. Both sides argued in good faith.

---

## 0. TL;DR (read this first)
1. **Our backend is FastAPI, not Django.** "Use Django auth" would mean **rewriting the backend** or running a **second Django service** just for login. So the honest question isn't "Supabase vs Django" — it's **"managed auth vs owning our auth,"** and the FastAPI-native way to own it is **FastAPI-Users** (or self-hosting Supabase's own auth).
2. **Supabase Auth is open-source and self-hostable.** So "own your auth / no lock-in" — the teammate's core point — **can be achieved without leaving Supabase Auth** (self-host GoTrue). This weakens the "we must switch to own it" argument.
3. **Owning auth is NOT automatically more secure.** Django's own `django-allauth` had **7 disclosed vulnerabilities** (2 enabling account takeover) and `simplejwt` had an access-control CVE. Owning it means **you** chase those patches.
4. **The real trade-off:** *control & data-ownership & no per-user cost* (own it) **vs** *less work, offloaded security ops, and DB-integrated row-level security* (managed Supabase).
5. **Recommendation (conditional, see §9):** For a pilot on this stack, **stay on Supabase Auth** and, if ownership becomes a hard requirement, **self-host Supabase GoTrue** — that satisfies the teammate's goal with the least risk. A full move to FastAPI-Users is defensible long-term but is a multi-day, security-critical migration. Switching the backend to Django is **not** worth it.

---

## 1. What Supabase Auth actually is (facts, not vibes)
- Supabase is an **open-source** Backend-as-a-Service built on PostgreSQL — positioned explicitly as a "Firebase alternative **without vendor lock-in**."
- Its auth component is **GoTrue** (Apache-2.0 licensed): handles email/password, magic links, phone OTP, OAuth (Google/GitHub/Apple/…), passkeys, anonymous sessions.
- It issues **JWTs signed with ES256**, which our FastAPI backend already verifies via the standard **JWKS** public-key endpoint.
- It integrates with Postgres **Row Level Security** via `auth.uid()` — a genuine security layer we already use.
- **Self-hostable:** GoTrue + PostgREST + Storage + Realtime + Postgres all run on your own servers via Docker. **Self-hosting is free.**
- **Pricing (2026):** Free tier = 50,000 MAU; Pro = $25/mo/project; then **$0.00325 per MAU** — among the cheapest managed options. Team = $599/mo (SOC 2, SSO).

**Implication:** Supabase Auth is not a closed black box. If the worry is *lock-in* or *dependence on their cloud*, you can **self-host the exact same auth** and keep all our existing code (JWKS, RLS, triggers) working.

---

## 2. What "owning our auth" actually means here
"Owning auth" = users live in **our own database**, and **we run the login code**. Three concrete ways to do it:

| Path | What it is | Fit for our FastAPI stack |
|---|---|---|
| **Django auth** (teammate's pick) | Django's mature built-in auth + `django-allauth`/`dj-rest-auth`/`simplejwt` | ❌ Requires **rewriting the backend to Django**, or running a **separate Django microservice** just for auth (two frameworks, more ops) |
| **FastAPI-Users** | The batteries-included auth **library for FastAPI** — register/login/reset/verify/JWT/OAuth, users in our Postgres | ✅ **Best native fit** — the true "Django-auth equivalent" for our stack |
| **Self-host Supabase GoTrue** | Run Supabase's own open-source auth on our servers | ✅ Own it **without rewriting anything** |

**Honest note on the teammate's claim "Django is best":** Django's auth *is* genuinely excellent — 20 years battle-tested, secure defaults, huge ecosystem. It is arguably the **best auth for a Django application.** But "best for Django" ≠ "best for a FastAPI app." Recommending Django here really means "let's own our auth," and the correct FastAPI expression of that is **FastAPI-Users**, not adopting a second web framework.

---

## 3. The teammate's case — stated fairly (why "own it" has real merit)
These are legitimate, experienced-engineer arguments:
1. **No vendor dependency.** If Supabase's cloud auth service has an incident, our logins fail and we can't fix it. Owning it puts uptime in our hands.
2. **Data ownership.** User records live in *our* database, fully under our control and residency.
3. **No per-user cost, ever.** Self-managed auth has no MAU billing — only our own server cost.
4. **Full control & customization.** Any login flow, field, or rule we want, without provider limits.
5. **Maturity.** Django's auth stack is extremely well-trodden; millions of production apps rely on it.
6. **Avoiding "auth as a scaling bottleneck"** — a real pattern where teams outgrow a managed provider's pricing/limits and migrate later anyway.

## 4. The counter-case — stated just as fairly
1. **Owning auth = owning its security forever.** Real evidence: `django-allauth` had **7 vulnerabilities** (2 → account takeover), and `djangorestframework-simplejwt ≤5.3.1` had an access-control CVE. Managed providers absorb this work for you.
2. **The hard parts are hidden.** Refresh-token rotation, token revocation (JWT is stateless — instant logout is genuinely hard), CSRF, secure cookie config, brute-force rate limiting (allauth's default cache **won't** rate-limit — a common misconfig). Getting these wrong is how breaches happen.
3. **"Own it" doesn't require *switching*.** Because Supabase Auth is open source, self-hosting GoTrue already delivers ownership — undercutting the need to migrate frameworks.
4. **We'd lose Supabase's RLS integration** (`auth.uid()`), a database-level safety net we currently have and just hardened.
5. **The reliability argument may be misaimed** (see §6).

---

## 5. Head-to-head comparison (our stack)
| Dimension | Supabase Auth (cloud, current) | Self-host Supabase GoTrue | FastAPI-Users (own, in FastAPI) | Django auth (switch backend) |
|---|---|---|---|---|
| Users stored in | Supabase `auth.users` | Our Postgres (we run it) | **Our Postgres** | Our Postgres (Django) |
| Fits FastAPI backend | ✅ native | ✅ (same tokens) | ✅ native library | ❌ needs rewrite/2nd service |
| Who owns security patching | Supabase | **Us (ops)** | **Us (library CVEs)** | **Us (library CVEs)** |
| Depends on 3rd-party uptime | Yes | **No** | **No** | **No** |
| Postgres RLS `auth.uid()` | ✅ built-in | ✅ kept | ❌ lost (app-code checks) | ❌ lost |
| Per-user cost | Free ≤50k, then $0.00325/MAU | $0 (our servers) | $0 | $0 |
| Ops burden | None | **Medium (run GoTrue)** | Medium | High (2 frameworks) |
| Migration effort from today | None | **Low–Medium** | **High** | **Very High** |
| Existing users keep passwords | ✅ | ✅ (same DB) | ❌ likely reset | ❌ reset |
| Maturity / battle-tested | High | High | Medium-High | **Very High** |
| Custom flows / control | Medium | High | High | **Highest** |

---

## 6. The reliability question (the actual trigger for this debate)
The incident was **"login/auth failed."** Two honest points:
- If the failure was in Supabase's **Auth service (GoTrue cloud)** → self-hosting GoTrue **or** owning auth would remove that dependency. Valid reason.
- **But** our users and app data live in **Supabase Postgres**. If the weak link is the **database** (free-tier pausing, a DB incident), then owning *auth* while keeping the *same database* **does not fix it** — and the cheapest real fix is **upgrading Supabase to Pro** (no auto-pause, better SLA), with **zero migration**.
- **Action item:** confirm *what* failed (Auth service vs DB) before choosing — it changes the answer.

---

## 7. Migration cost & risk (if we move off Supabase Auth)
Applies to FastAPI-Users or Django (not to self-hosting GoTrue, which is far cheaper):
- Move users to our own `users` table; **drop the `auth.users` foreign key**.
- **Rewrite every RLS policy** that uses `auth.uid()`; replace the `handle_new_user` trigger.
- Rebuild **admin user creation** (currently via Supabase admin API) and the **frontend** login/signup (currently `supabase-js`).
- **Migrate existing users** — password hashes usually can't transfer, so **users must reset passwords**.
- Re-implement **email verification + password reset** (needs SMTP — we're already setting up Resend).
- Re-add **MFA, rate limiting, refresh-token rotation** ourselves.
- **Risk:** this is security-critical surgery, immediately after we hardened auth. Estimated **several focused days**, not a single day.

---

## 8. Cost snapshot (2026, for scale context)
| Provider | Free tier | Cost after |
|---|---|---|
| Supabase Auth | 50,000 MAU | $0.00325 / MAU |
| Self-host GoTrue / FastAPI-Users / Django | "free" (your server/ops time) | server + engineering upkeep |
| Firebase Auth | 50,000 MAU | ~$0.0055 / MAU |
| Clerk | 50,000 MRU | ~$0.02 / user |
| Auth0 | ~25,000 MAU | $35–$240+/mo |

For our **pilot scale**, auth cost is effectively **₹0 on Supabase** — cost is not currently a reason to switch.

---

## 9. Decision framework — pick based on the *real* goal
- **Goal = "fix the login reliability incident"** → First find out if it was Auth or DB (§6). If DB/free-tier → **upgrade Supabase (stay on Supabase Auth)**. Cheapest, safest.
- **Goal = "own our auth / no vendor dependency"** → **Self-host Supabase GoTrue.** Achieves ownership with **minimal rewrite** and keeps RLS. Best value for the teammate's concern.
- **Goal = "long-term, everything in our own FastAPI backend"** → **FastAPI-Users.** Legit, but plan a **multi-day migration** and accept losing RLS `auth.uid()`.
- **Goal = "use Django because it's proven"** → Only if we were **already a Django app**. We're not, so **not recommended** — the rewrite/second-service cost outweighs the benefit.

## 10. Honest recommendation
For where this project is **today** (pilot, FastAPI, deeply integrated with Supabase Postgres + RLS that we just hardened):
1. **Stay on Supabase Auth for now.** It's open-source-backed (real exit path), cheap, integrated, and works.
2. **If the login incident recurs or ownership becomes a hard requirement → self-host Supabase GoTrue** (own it, minimal change).
3. **Consider FastAPI-Users only** if we make a deliberate long-term decision to own everything in FastAPI — as a planned migration, not a reaction.
4. **Do not switch the backend to Django**, and **do not hand-roll auth** from scratch.

The teammate's instinct — *don't be over-dependent on a vendor* — is **valid and worth respecting**. The key insight is that **Supabase Auth's open-source nature already gives us that ownership option**, so we can honor the concern **without** a costly framework switch.

## 11. Questions to resolve together (this settles it)
1. **What exactly failed** — Supabase's Auth service, or the database? *(Decides whether switching auth even helps.)*
2. Is our real goal **reliability**, **ownership/no-lock-in**, **cost**, or **control**? *(Each points to a different answer above.)*
3. Are we prepared to **own security upkeep** (CVE patching, token rotation, incident response) if we self-manage?
4. Do we accept a **multi-day migration where all users reset passwords** (FastAPI-Users/Django)?
5. Would **self-hosting Supabase GoTrue** satisfy the ownership concern with far less risk?

---

### Sources (2026)
- Supabase Auth / GoTrue (open-source, self-hostable, pricing): https://guptadeepak.com/ciam-compass/vendors/supabase-auth/ · https://automationatlas.io/answers/supabase-pricing-explained-2026/
- FastAPI auth options (FastAPI-Users, pwdlib/PyJWT/Argon2): https://workos.com/blog/top-authentication-solutions-fastapi-2026 · https://github.com/fastapi-users/fastapi-users
- Django auth options (allauth/dj-rest-auth/simplejwt) + security: https://workos.com/blog/top-authentication-solutions-django-2026 · https://zeropath.com/blog/django-allauth-account-takeover-vulnerabilities
- Build-vs-buy / self-hosted auth 2026: https://supertokens.com/blog/self-hosted-auth-solutions-in-2026
