# AI Quiz Generator Platform — Project Workflow Document

**Document Type:** Project Overview & Workflow Specification
**Version:** 1.0
**Date:** August 2026
**Prepared By:** [Your Name]
**For:** [Manager Name] / Leadership Review
**Project Codename:** quiz-generator-v1

---

## 1. Executive Summary

### 1.1 What we are building

An AI-powered, multi-tenant SaaS quiz generator platform for
educational institutions. Teachers upload teaching material (PDFs,
Word documents), our AI generates high-quality quiz questions across
multiple formats and difficulty levels, teachers review and approve
the questions, and students take the quizzes on a mobile-friendly
web interface.

### 1.2 The business opportunity

Educational institutions across India — CA/CMA/ACCA coaching centers,
JEE/NEET coaching centers, commerce colleges, and general educational
institutions — spend significant faculty hours creating quizzes
manually from textbooks and past papers. Our platform reduces this
work from hours to minutes while maintaining teacher-controlled
quality via a mandatory review step.

### 1.3 Phase 1 pilot customer

**ArivuPro Academy** will be the first pilot customer (internal
tenant). Phase 1 will validate the product with ArivuPro faculty
before we open it up as a SaaS to external institutions in Phase 2.

### 1.4 Timeline overview

- **Design phase:** 2 weeks
- **Development phase:** 6–8 weeks
- **ArivuPro pilot:** 4 weeks
- **Phase 2 (external launch prep):** starts after pilot success
- **Total time to first external customer:** ~4 months

---

## 2. Product Vision & Scope

### 2.1 Product principles

1. **Teacher-controlled quality.** AI generates, teachers approve.
   No AI-generated content reaches students without teacher review.
2. **Student choice.** Multiple quiz variants per topic (Theory /
   Practical / Mixed) so students can practice what they need.
3. **Institution-agnostic.** Works for any exam type — CA, JEE,
   NEET, B.Com, arts, sciences — because the AI understands the
   uploaded material, not a pre-baked syllabus.
4. **Mobile-first.** Students take quizzes on their phones. The
   platform is responsive from day one.
5. **Multi-tenant from day one.** Every institution's data is
   isolated. No cross-tenant leakage is possible.

### 2.2 What Phase 1 delivers

- Multi-tenant SaaS platform (ArivuPro as first tenant)
- Teacher upload → AI generation → teacher review → student quiz flow
- 6 question types (MCQ, Multiple Select, True/False, Fill in the
  Blank, Numerical, Matching)
- 3 cognitive levels (Theory / Theory-to-Practical / Practical)
- Quiz Sets pattern (multiple variants per topic)
- Auto-grading and score display
- Basic analytics for teachers

### 2.3 What is explicitly NOT in Phase 1

Deferred to Phase 2 or later:
- Custom subdomains per institution (white-labeling)
- Subscription and billing engine
- AI Tutor for post-quiz explanations
- Adaptive difficulty
- Timed mock exams with negative marking
- Image and diagram OCR from PDFs
- Formula OCR (LaTeX conversion)
- Excel bulk import/export
- Native mobile apps (responsive web is sufficient)
- Live proctoring

---

## 3. User Roles & Permissions

### 3.1 Four user roles

| Role | Scope | Primary responsibilities |
|---|---|---|
| **Super Admin** | Platform-wide (ArivuPro) | Manages all tenant institutions, monitors platform usage, resolves cross-tenant issues |
| **Institute Admin** | Within their institution | Manages teachers and students for their institution, views institutional usage |
| **Teacher** | Within their institution | Uploads material, generates quizzes, reviews and approves, publishes to students |
| **Student** | Within their institution | Takes quizzes assigned to them, views scores and results |

### 3.2 Permissions matrix

| Action | Super Admin | Institute Admin | Teacher | Student |
|---|:-:|:-:|:-:|:-:|
| Manage tenant institutions | ✓ | – | – | – |
| Manage users in their institution | ✓ | ✓ | – | – |
| Upload documents | ✓ | – | ✓ | – |
| Generate quizzes with AI | ✓ | – | ✓ | – |
| Review/approve/reject questions | ✓ | – | ✓ | – |
| Publish quizzes | ✓ | – | ✓ | – |
| Take quizzes | – | – | – | ✓ |
| View institution analytics | ✓ | ✓ | ✓ (own classes) | – |
| View platform-wide analytics | ✓ | – | – | – |

---

## 4. Core Product Workflow

### 4.1 End-to-end user journey

```
┌───────────────────────────────────────────────────────────────┐
│                    STAGE 1: SETUP                             │
│  Super Admin onboards a new institution (tenant)              │
│  Institute Admin adds teachers and students to their tenant   │
│  Users receive invitations, sign up, land on their dashboards │
└───────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────┐
│              STAGE 2: TEACHER GENERATES QUIZ                  │
│  Teacher logs in                                              │
│  Selects a course/subject (e.g. "CA Foundation - Bus. Maths") │
│  Uploads teaching material (PDF or DOCX)                      │
│  Waits ~30 seconds while AI processes the document            │
│  Configures quiz generation options:                          │
│    - Number of questions per variant (10, 20, 30)             │
│    - Question types to include (from the 6 supported)         │
│    - Cognitive level focus (Theory / Practical / Mixed)       │
│    - Difficulty (Easy / Medium / Hard)                        │
│  AI generates a Quiz Set with 3-4 variants                    │
└───────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────┐
│              STAGE 3: TEACHER REVIEWS QUIZ                    │
│  Teacher enters the review interface                          │
│  For each variant, reviews all questions:                     │
│    - Approve (thumbs up)                                      │
│    - Edit (fix wording, options, correct answer)              │
│    - Reject (delete this question)                            │
│    - Regenerate (ask AI for a new version)                    │
│  Once satisfied, publishes the Quiz Set                       │
└───────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────┐
│           STAGE 4: STUDENT TAKES QUIZ                         │
│  Student sees "New Quiz Available" on dashboard               │
│  Opens the Quiz Set, sees available variants:                 │
│    - "Theory Practice"                                        │
│    - "Application Practice"                                   │
│    - "Problem-Solving Practice"                               │
│    - "Mixed Practice"                                         │
│  Picks a variant based on their study need                    │
│  Attempts the quiz on web/mobile                              │
│  Submits and sees score immediately                           │
└───────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────┐
│         STAGE 5: TEACHER SEES RESULTS                         │
│  Teacher sees aggregate student performance                   │
│  Which questions students struggled with                      │
│  Class average, top/bottom performers                         │
│  Feedback loop for teaching adjustments                       │
└───────────────────────────────────────────────────────────────┘
```

### 4.2 The "Quiz Sets" design pattern

Instead of the teacher generating one quiz, they generate **multiple
variants of the same topic simultaneously.** Each variant tests the
same content at a different cognitive level.

**Example — Topic: Compound Interest**

- **Variant A: Theory Practice** — 10 questions on definitions and
  formulas ("What is the formula for compound interest?")
- **Variant B: Application Practice** — 10 questions applying the
  concept to standard problems ("Calculate interest on ₹10,000 at
  8% for 3 years")
- **Variant C: Problem-Solving Practice** — 10 questions requiring
  multi-step analysis ("A company invests in 3 assets with different
  rates — find the optimal allocation")
- **Variant D: Mixed Practice** — 10 questions blending all three levels

**Why this is powerful:**
- Teacher reviews all four variants in one sitting (efficient)
- Students choose the variant matching their current study need
  (personalized)
- One document upload produces 4x the value (economical)

### 4.3 Question types supported

Six auto-gradeable question types, all mobile-friendly:

1. **Multiple Choice (Single Answer)** — 4 options, 1 correct
2. **Multiple Select** — 4 options, more than 1 correct
3. **True / False** — 2 options
4. **Fill in the Blank** — student types the missing word/phrase
5. **Numerical** — student enters a numeric answer
6. **Matching (Tabular MCQ)** — match Column A ↔ Column B, student
   picks the correct permutation from 4 options

---

## 5. System Architecture Overview

### 5.1 High-level architecture

```
┌────────────────────────────────────────────────────────────────┐
│                    USER'S BROWSER / PHONE                       │
│              (Students, Teachers, Admins)                       │
└────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS
                              ▼
┌────────────────────────────────────────────────────────────────┐
│                     FRONTEND (Vercel)                           │
│        Next.js 14 + TypeScript + Tailwind CSS                   │
│  - Login / Signup pages (per role)                              │
│  - Teacher dashboard (upload, review, publish)                  │
│  - Student dashboard (available quizzes, take quiz)             │
│  - Admin dashboards (user management, analytics)                │
└────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┼──────────┐
                    │         │          │
                    ▼         ▼          ▼
┌───────────────────────┐  ┌─────────────────────────────────────┐
│  SUPABASE             │  │      BACKEND (Railway)              │
│  Auth + Database +    │  │      Python + FastAPI               │
│  File Storage         │  │                                     │
│                       │  │  - AI processing endpoints          │
│  - User authentication│  │  - Document parsing                 │
│  - PostgreSQL data    │  │  - Quiz generation orchestration    │
│  - Uploaded PDF/DOCX  │  │  - Auto-grading engine              │
│  - RLS for multi-tenancy│  │                                   │
└───────────────────────┘  └─────────────────────────────────────┘
                                            │
                                            ▼
                              ┌──────────────────────────────────┐
                              │       AI LAYER                   │
                              │                                  │
│  Primary: Google Gemini          │
│  (provider abstraction)          │
                              │                                  │
│  Fallback: DeepSeek              │
│  (when Gemini is unavailable)    │
                              └──────────────────────────────────┘
```

### 5.2 Data flow — quiz generation

```
1. Teacher uploads PDF via frontend
2. Frontend sends file to backend API (/api/documents/upload)
3. Backend saves file to Supabase Storage
4. Backend extracts text using pdfplumber (or Tesseract OCR fallback)
5. Text is chunked into manageable sections
6. Backend sends chunks + quiz parameters to the configured AI provider
7. The provider returns structured JSON with questions
8. Backend validates the JSON and stores questions in database
9. Frontend displays Quiz Set to teacher for review
```

### 5.3 Data flow — student taking quiz

```
1. Student logs in, sees dashboard
2. Frontend queries: SELECT quizzes WHERE published = true
   AND tenant_id matches student's tenant (RLS enforced)
3. Student picks a variant, clicks "Start Quiz"
4. Frontend loads questions from database
5. Student answers each question
6. Frontend submits answers to backend (/api/submissions/create)
7. Backend auto-grades against stored correct answers
8. Backend saves submission and score
9. Frontend displays score and results
```

### 5.4 Multi-tenancy — how data is isolated

Every table in the database has a `tenant_id` column. When a user
logs in, their session token contains their `tenant_id`. PostgreSQL's
**Row Level Security (RLS)** automatically filters every query to
only return rows matching the user's `tenant_id`.

**Effect:** An ArivuPro teacher can never see XYZ Coaching's data.
Even if they try to access `/api/quizzes/some-xyz-quiz-id` directly,
the database refuses to return the row. Data leakage is impossible
at the database level, not just the application level.

---

## 6. Technology Stack

### 6.1 Full stack summary

| Layer | Technology | Reasoning |
|---|---|---|
| **Frontend Framework** | Next.js 14 + TypeScript | Modern React, SSR, one codebase for all interfaces |
| **Styling** | Tailwind CSS + shadcn/ui | Fast, consistent, professional-looking UIs |
| **Backend Language** | Python 3.11+ | Best ecosystem for AI/data work |
| **Backend Framework** | FastAPI | Async, modern, LLM-friendly |
| **Database** | PostgreSQL (via Supabase) | Industry standard, RLS built-in |
| **Authentication** | Supabase Auth | Free until 50K users, integrated |
| **File Storage** | Supabase Storage | Integrated with auth and database |
| **Primary AI** | Google Gemini | Primary provider for generation and extraction |
| **Fallback AI** | DeepSeek | Used when Gemini is unavailable |
| **PDF Processing** | pdfplumber + Tesseract OCR | Standard tools, free |
| **Frontend Hosting** | Vercel | Optimized for Next.js |
| **Backend Hosting** | Railway | Runs the FastAPI Docker service |
| **Version Control** | GitHub | Industry standard |
| **CI/CD** | GitHub Actions | Automated deployments |

### 6.2 Cost estimate — Phase 1 pilot

| Service | Monthly Cost |
|---|---|
| Supabase (Free tier) | ₹0 |
| Vercel (Free tier) | ₹0 |
| DeepSeek API (pilot volume) | ~₹800–1,600 |
| Claude API (fallback only) | ~₹400–800 |
| Domain (annual) | ~₹80 |
| **Total** | **~₹1,500–2,500 / month** |

### 6.3 Cost projection — post-pilot scale

At 10 active tenant institutions with ~500 total teachers generating
~2,000 quiz sets per month:

| Service | Monthly Cost |
|---|---|
| Supabase Pro | ₹2,100 |
| Vercel Pro | ₹1,700 |
| DeepSeek API | ~₹5,000 |
| Claude API | ~₹3,000 |
| **Total** | **~₹12,000 / month** |

Unit economics allow charging institutions ₹5,000–15,000/month per
tenant, providing healthy margins even at low scale.

---

## 7. Development Roadmap

### 7.1 Phase 1 breakdown (6–8 weeks total)

**Week 1–2: Architecture Design**
- Database schema design
- AI pipeline design
- Authentication flow design
- API endpoint design
- Frontend routing and component structure

**Week 3: Slice 1 — Foundation**
- Supabase setup (tables, RLS policies, auth)
- Basic frontend routing
- Login/signup flows for all four roles
- Tenant creation and user invitation

**Week 4: Slice 2 — Document Upload**
- Teacher document upload interface
- Backend file receiver and storage
- Text extraction pipeline (PDF + DOCX)
- Extracted text preview for teacher

**Week 5: Slice 3 — AI Quiz Generation**
- LLM provider abstraction layer
- Prompt engineering for 6 question types × 3 cognitive levels
- Quiz Set generation orchestration
- Cost tracking per generation

**Week 6: Slice 4 — Teacher Review Interface**
- Approve / Edit / Reject / Regenerate UI
- Question editing forms per type
- Publish workflow

**Week 7: Slice 5 — Student Quiz-Taking**
- Student dashboard
- Quiz variant selection UI
- Quiz-taking interface (all 6 question types)
- Auto-grading engine
- Score display

**Week 8: Slice 6 — Polish + Deploy**
- Bug fixes based on internal testing
- Performance optimization
- Production deployment
- Documentation for pilot users

### 7.2 Post-Phase 1 (Pilot & Iteration — 4 weeks)

- ArivuPro faculty and students use the platform
- Daily standups with pilot users to catch issues
- Iteration on real feedback
- Success criteria evaluation

### 7.3 Phase 2 Roadmap (Post-Pilot)

- Custom subdomain per institution
- White-labeling (institutional branding)
- Subscription and billing engine
- External institution onboarding
- Advanced analytics dashboards

### 7.4 Phase 3 Roadmap (Long-term)

- AI Tutor for post-quiz explanations
- Adaptive difficulty based on student performance
- Timed mock exams with exam simulator
- Advanced question types (Short Answer with AI grading)
- Native mobile apps

---

## 8. Success Criteria — Phase 1

Phase 1 is considered successful when:

1. **Adoption:** ≥3 ArivuPro faculty actively use the platform
2. **Volume:** ≥15 Quiz Sets generated across ≥3 different courses
3. **Student engagement:** ≥30 students take ≥1 quiz each
4. **Quality:** ≥70% of AI-generated questions approved without edits
5. **Efficiency:** Average teacher review time <10 min per Quiz Set
6. **Reliability:** ≥99% system uptime during pilot
7. **Satisfaction:** Faculty rating ≥7/10 on "would you keep using this"
8. **Cost discipline:** Monthly infrastructure cost <₹5,000

---

## 9. Risks & Mitigations

### 9.1 Technical risks

| Risk | Likelihood | Impact | Mitigation |
|---|:-:|:-:|---|
| AI generates incorrect questions | High | Medium | Mandatory teacher review before student sees anything |
| Gemini API unreliability | Medium | Medium | DeepSeek automatic fallback |
| Uploaded PDFs are scanned images | Medium | Low | Tesseract OCR fallback for image-based PDFs |
| Multi-tenant data leakage bug | Low | High | Postgres Row Level Security enforced at DB level |
| Vercel serverless cold-start latency | Medium | Low | Migrate to Railway/Fly.io if timing becomes an issue |

### 9.2 Product risks

| Risk | Likelihood | Impact | Mitigation |
|---|:-:|:-:|---|
| Faculty won't adopt (change resistance) | Medium | High | Pilot with pre-committed faculty; user feedback loops |
| Question quality varies by subject | High | Medium | Teacher review acts as quality gate |
| Students don't use variant choice feature | Low | Low | Even with one variant, product is valuable |

### 9.3 Business risks

| Risk | Likelihood | Impact | Mitigation |
|---|:-:|:-:|---|
| Chinese AI (DeepSeek) causing customer concerns | Medium | Medium | Have Claude fallback as "Premium" tier option |
| Competitor launches first | Medium | Medium | Focus on speed to market, ArivuPro's domain expertise |
| Institutions demand features we deferred to Phase 2 | High | Medium | Clear roadmap communication; premium waitlist |

---

## 10. Team & Roles

**Development Team:**
- [Your Name] — Lead Developer (full-stack, AI integration)
- [Team Lead Name] — Technical Lead
- [Your Recruiting Manager] — Recruiting Manager
- [Your Manager] — Product Manager / Sponsor

**Pilot Team (ArivuPro):**
- To be identified — 2–3 pilot faculty
- Institutional Admin liaison

**Advisory:**
- AI/ML mentor (external, via Claude "learn-and-build" skill)

---

## 11. Appendix

### 11.1 Glossary

- **Tenant:** An institutional customer of our platform (e.g. ArivuPro)
- **Multi-tenant:** Architecture allowing many institutions to share
  the same platform with data isolation
- **RLS (Row Level Security):** PostgreSQL feature that enforces
  data isolation at the database level
- **Quiz Set:** A collection of quiz variants generated from one document
- **Quiz Variant:** A specific version of a Quiz Set focused on one
  cognitive level (Theory / Practical / Mixed)
- **Cognitive Level:** Simplified Bloom's Taxonomy — Theory,
  Theory-to-Practical, Practical
- **LLM:** Large Language Model — the AI that generates quiz questions
- **Slice:** A vertical feature increment shipped end-to-end

### 11.2 Related documents

- `scoping-quiz-generator-v1-v2-LOCKED.md` — Detailed technical scoping
- `database-schema.md` — Full database schema (in progress)
- Original SRS: `ArivuPro_SRS_v2_MultiTenant.docx` (superseded by
  this document for Phase 1)

### 11.3 Approval

This document represents the agreed-upon workflow for Phase 1 of
the AI Quiz Generator Platform. Any changes to scope, roadmap, or
technology stack should be reviewed and approved before implementation.

**Approvals needed:**
- [ ] Technical Lead
- [ ] Product Manager / Sponsor
- [ ] Recruiting Manager

---

*End of Document*
