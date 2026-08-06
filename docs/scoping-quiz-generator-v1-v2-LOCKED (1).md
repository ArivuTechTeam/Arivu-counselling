# Scoping: quiz-generator-v1 (SaaS Product — Phase 1)

**Status:** SCOPING + TECH STACK LOCKED — ready for architecture design
**Version:** v2 (updated after tech stack discussion)
**Date locked:** 2026-07-31
**Owner:** [user]
**Mentor:** Senior FDE (learn-and-build skill)

---

## 1. Problem

Educational institutions (CA coaching centers, JEE/NEET coaching centers,
commerce and arts colleges, and similar) spend significant time creating
quizzes manually for their students. Teachers type MCQs from textbooks,
past papers, and their own material — a slow, repetitive process that
takes hours per chapter.

Phase 1 aims to give teachers at any educational institution an
AI-powered tool that generates chapter-specific quizzes from their own
uploaded teaching material, with teacher review to ensure quality, and
student-facing quiz variants for different learning objectives.

---

## 2. Product model

**Type:** B2B SaaS product
**Positioning:** Generic AI quiz generator for educational institutions
**First customer (pilot):** ArivuPro Academy (internal use)
**Target customer segments (post-pilot):** CA coaching centers, JEE/NEET
coaching centers, commerce colleges, general educational institutions
**Business model:** Subscription-based (details in Phase 2)

---

## 3. User roles (Phase 1)

**Teacher:**
- Uploads teaching material (PDF, DOCX)
- Selects quiz generation options (types, difficulty, cognitive level)
- Reviews AI-generated questions (approve / edit / reject / regenerate)
- Publishes Quiz Sets to students
- Views quiz results and student performance

**Student:**
- Sees available Quiz Sets on dashboard
- Chooses which quiz variant to attempt (Theory / Practical / Mixed)
- Takes quiz online (mobile-friendly)
- Sees score and results after submission

**Institution Admin:**
- Manages teacher and student accounts within their institution
- Views institutional usage
- Basic settings

**Super Admin (ArivuPro platform level):**
- Manages tenant institutions
- Platform-wide monitoring

---

## 4. Core workflow

```
Teacher uploads document (PDF/DOCX)
    ↓
AI extracts text and understands content
    ↓
Teacher selects generation options:
    - Number of questions per variant (5, 10, 20, 30)
    - Question type mix (from 6 supported types)
    - Cognitive level: Theory / Theory-to-Practical / Practical / Mixed
    - Difficulty (Easy / Medium / Hard)
    ↓
AI generates a Quiz Set with multiple variants:
    - Variant A: Theory-focused
    - Variant B: Theory-to-Practical
    - Variant C: Practical
    - Variant D: Mixed
    ↓
Teacher reviews all variants:
    - Approves / Edits / Rejects individual questions
    - Regenerates specific questions if needed
    ↓
Teacher publishes the Quiz Set
    ↓
Students see published Quiz Set on their dashboard
    ↓
Student picks one variant to attempt
    ↓
Student takes quiz (auto-graded)
    ↓
Student sees score and results
    ↓
Teacher sees aggregate student performance
```

---

## 5. Question types supported (Phase 1)

**6 types, all auto-gradeable, all mobile-friendly:**

1. **MCQ (Single Answer)** — 4 options, 1 correct
2. **Multiple Select** — 4 options, more than 1 correct
3. **True / False** — 2 options
4. **Fill in the Blank** — sentence with blank, student types answer
   (fuzzy-matched grading)
5. **Numerical** — student types a numeric answer (with tolerance range)
6. **Matching (Tabular MCQ)** — Column A ↔ Column B match-the-following,
   student picks correct permutation from 4 MCQ-style options

**Explicitly excluded from Phase 1:**
- Short Answer / Essay (grading is unreliable)
- Drag-and-drop matching (UI complexity, low ROI)

---

## 6. Cognitive levels (Simplified Bloom's Taxonomy)

Every Quiz Set variant is tagged with a cognitive level:

- **Theory (Level 1)** — Recall / conceptual understanding
- **Theory-to-Practical (Level 2)** — Application to standard problems
- **Practical (Level 3)** — Multi-step problem solving

Teacher can request variants at specific levels or a mixed variant.

---

## 7. Tech Stack (LOCKED after full discussion)

### Backend
| Component | Choice | Reasoning |
|---|---|---|
| Language | Python 3.11+ | Ecosystem for AI/data work |
| Framework | FastAPI | Async, modern, LLM-friendly |
| ORM | **SQLModel** | Better than SQLAlchemy for FastAPI, Pydantic-integrated |
| Migrations | Alembic | Version-controlled schema changes |
| Data validation | Pydantic | Native to FastAPI |

### Database + Auth + Storage (Supabase)
| Component | Choice | Reasoning |
|---|---|---|
| Database | **PostgreSQL via Supabase** | Standard Postgres, portable, RLS built-in |
| Auth | **Supabase Auth** | Free until 50K users, integrated with DB |
| File Storage | **Supabase Storage** | For uploaded PDFs/DOCX |
| Row Level Security | Supabase RLS policies | Multi-tenant data isolation |

### AI Layer
| Component | Choice | Reasoning |
|---|---|---|
| Primary LLM | **DeepSeek V4** | ~50x cheaper than Claude, good quality |
| Fallback LLM | **Claude Sonnet 5** | Reliable when DeepSeek fails |
| Abstraction Layer | Custom `LLMProvider` interface | Never hardcode a specific provider |

**AI routing strategy:**
```
Try DeepSeek V4 first
    ├─ Success → return response
    └─ Fail / rate limit / quality check fails
        └─ Fallback to Claude Sonnet 5
```

**Explicitly NOT using:** OpenAI, LangChain, LlamaIndex

### Document Processing
| Component | Choice | Reasoning |
|---|---|---|
| Text PDF | pdfplumber | Standard, reliable |
| Word docs | python-docx | Standard for .docx |
| Scanned PDFs | Tesseract OCR | Fallback for image-based PDFs |

### Frontend
| Component | Choice | Reasoning |
|---|---|---|
| Framework | Next.js 14+ (App Router) | Modern React, SSR, one codebase |
| Language | TypeScript | Type safety |
| CSS | Tailwind CSS | Utility-first, fast development |
| UI Components | shadcn/ui | Copy-paste components, customizable |
| State management | React state + TanStack Query | No Redux needed at this scale |

### Deployment
| Component | Choice | Reasoning |
|---|---|---|
| Frontend hosting | **Vercel** | Optimized for Next.js, global CDN |
| Backend hosting | **Vercel** (initially) | Python serverless functions |
| Fallback backend | Railway or Fly.io | If Vercel cold starts fail |
| Database hosting | Supabase (managed) | All-in-one |
| Domain/DNS | Cloudflare (recommended) | Free, fast |

### Dev Tooling
- **VS Code** with Python, Pylance, Ruff, ESLint, Prettier, Tailwind extensions
- **uv** for Python package management (faster than pip)
- **pnpm** for Node package management
- **Git + GitHub** for version control
- **GitHub Actions** for CI/CD

---

## 8. Portability principles (avoid vendor lock-in)

To maintain ability to migrate off Supabase later if needed:

1. Write all queries via SQLModel (works with any PostgreSQL host)
2. Use Supabase Auth JWT tokens but design portable permission logic
3. Store files via abstraction layer (works with Supabase Storage OR S3)
4. Avoid Supabase-only features (edge functions, real-time subscriptions
   in Phase 1)
5. Standard PostgreSQL migrations via Alembic

**Result:** ~99% portable to any PostgreSQL host in 1-2 weeks if needed.

---

## 9. Multi-tenancy foundational rules (non-negotiable from day one)

1. **Every table has `tenant_id` column** — even for single-tenant pilot
2. **Row Level Security policies enforced** — no cross-tenant data leaks
3. **JWT tokens carry `tenant_id`, `user_id`, `role`** claims
4. **API routes include tenant context** — e.g. `/api/v1/tenants/:tenant_id/quizzes/`
5. **Indexes on all `tenant_id` columns** and foreign keys
6. **Files stored in object storage**, not database blobs
7. **Alembic migrations from day one** — every schema change versioned
8. **Environment separation** — dev / staging / prod

---

## 10. Ugliest v1 scope

**In scope:**
- Teacher signup/login (via Supabase Auth)
- Student signup/login (invited by teacher/institution)
- Institution admin (basic user management)
- Document upload (PDF/DOCX) → Supabase Storage
- AI text extraction and understanding
- Quiz Set generation (6 question types × 3 cognitive levels)
- Multiple variants per Quiz Set (Theory / Practical / Mixed)
- Teacher review interface (approve/edit/reject/regenerate)
- Quiz publishing
- Student dashboard (list of available quizzes)
- Student quiz-taking interface (mobile-friendly)
- Auto-grading for all 6 question types
- Score display + basic result view
- Multi-tenant architecture (ArivuPro = tenant #1)

---

## 11. Out of scope for Phase 1

- Custom subdomains per institution (Phase 2)
- White-labeling / custom branding (Phase 2)
- Subscription/billing engine (Phase 2)
- AI Tutor for post-quiz explanations
- Adaptive quiz difficulty
- Timed mock exams with negative marking
- Image/diagram extraction from PDFs
- Formula OCR / LaTeX conversion
- Excel bulk question import/export
- Detailed institutional analytics dashboards
- Native mobile apps (responsive web only)
- Duplicate detection with semantic embeddings
- Short Answer / Essay question types
- Live proctoring
- Payment gateways
- Real-time collaboration features

---

## 12. Success criteria for Phase 1

- ArivuPro Academy successfully uses the platform internally
- At least 3 ArivuPro teachers generate and publish Quiz Sets
- At least 30 students take at least one quiz
- Teacher review time under 10 minutes per Quiz Set (~40 questions
  across 4 variants)
- 70%+ of AI-generated questions get approved without edits
- System uptime 99%+ during pilot
- Teachers rate the tool 7/10 or higher on "would you keep using this"
- Monthly infrastructure cost under $100 during pilot

---

## 13. Cost estimate (Phase 1 pilot)

| Service | Cost |
|---|---|
| Supabase | $0 (free tier) |
| Vercel | $0 (free tier) or $20 (Pro) |
| DeepSeek API | ~$10-20/month |
| Claude API (fallback) | ~$5-10/month |
| Domain | ~$1/month ($10/year) |
| **Total** | **~$30-50/month** |

---

## 14. Development roadmap

**Phase 1 (current — 6-8 weeks):**
- Everything in "In scope"
- Ship to ArivuPro as first pilot tenant

**Phase 2 (after Phase 1 is stable):**
- Custom subdomains per institution
- White-labeling / branding
- Subscription and billing engine
- External customer onboarding
- Advanced analytics dashboards

**Phase 3 (later):**
- AI Tutor for post-quiz explanations
- Adaptive quizzes based on student performance
- Timed mock exams with negative marking
- Advanced question types (Short Answer with LLM grading)

---

## 15. Next architecture decisions

To be designed in future sessions:

- Complete database schema for multi-tenant Quiz Sets
- AI prompt engineering strategy for 3 cognitive levels
- LLM provider abstraction layer design
- File upload and storage flow
- Auth flow with Supabase (JWT structure, roles, permissions)
- API endpoint structure and versioning
- Frontend routing and component structure
- Cost monitoring and optimization strategy
- Deployment pipeline (CI/CD)

---

## 16. Non-goals

- Not a full LMS (not competing with Moodle, Canvas, Learnyst)
- Not a course delivery platform (no video lectures, no course content)
- Not a marketplace for content
- Not an exam proctoring tool
- Not a live-class platform
- Not a study-planner app

---

## 17. Working mode (hybrid)

User is a fresher on their first production project. Working mode is
hybrid, committed by phase:

**Architecture-only mode (for design phases):**
- Database schema design
- AI pipeline design
- Auth flow design
- API structure design
- Frontend structure design
- Deployment architecture

For these, skill designs and explains, user reasons through decisions
and executes (creates tables in Supabase, sets up services, etc.).

**Full build mode (for coding phases):**
- Slice-by-slice implementation
- Skill writes code, user adapts and deploys
- User's non-negotiable rule: never copy code they don't understand
- After each slice ships, quick review to confirm understanding

**Exceptions (revert to architecture-only within a slice) when:**
- Foundational concepts appear (auth, RLS, multi-tenancy patterns)
- Business logic critical to product correctness (grading, prompt
  engineering)
- Anything the user needs to debug alone at 11pm someday

**User's growth commitment:**
Never accept code they can't explain. Always be able to describe what
every line of their codebase does.

---

## Next step

User will start a fresh Claude session with the `learn-and-build` skill,
attach this scoping doc, and begin the architecture design phase —
starting with the database schema for multi-tenant Quiz Sets.
