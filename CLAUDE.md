# Quiz Generator v1 — Project Context

## What this project is
A multi-tenant SaaS quiz generator platform for educational institutions.
Teachers upload teaching material (PDFs, DOCX), AI generates quiz questions,
teachers review and approve, students take the quizzes.

Full project context is in docs/scoping-quiz-generator-v1-v2-LOCKED.md and 
docs/project-workflow-document.md — read those before making design decisions.

## Tech Stack (LOCKED — do not suggest alternatives)
- Backend: Python 3.11+ with FastAPI
- Frontend: Next.js 14+ with TypeScript, Tailwind CSS, shadcn/ui
- Database: PostgreSQL via Supabase
- Auth: Supabase Auth (JWT-based)
- File Storage: Supabase Storage
- Primary LLM: DeepSeek V4 (via API abstraction layer)
- Fallback LLM: Anthropic Claude Sonnet 5
- ORM: SQLModel (not raw SQLAlchemy)
- Deployment: Vercel for both frontend and backend

## Architecture Decisions (LOCKED)
- Multi-tenant with `tenant_id` on every table
- Row Level Security (RLS) enforces isolation
- ArivuPro is tenant #1 (not special-cased)
- ONE users table with role column (super_admin, institution_admin, teacher, student)
- Profiles table extends auth.users via 1:1 FK
- 6 question types: mcq_single, mcq_multi, numerical, true_false, fill_blank, matching (tabular MCQ)
- 3 cognitive levels: theory, practical, mixed
- Quiz Sets pattern: one upload generates multiple variants
- LLM provider abstraction — never hardcode DeepSeek or Claude

## Working Mode
- I am a fresher on my first production project
- Explain concepts before writing code
- Write code that I can understand and maintain
- Never use libraries or patterns without explaining why
- Prefer standard patterns over clever ones

## Folder Structure
quiz-generator-v1/
├── backend/ # FastAPI Python code
│ ├── app/
│ │ ├── api/ # API routes
│ │ ├── models/ # SQLModel definitions
│ │ ├── services/ # Business logic
│ │ └── main.py
│ ├── tests/
│ ├── requirements.txt
│ └── .env
├── frontend/ # Next.js code
│ ├── app/ # App Router pages
│ ├── components/ # React components
│ ├── lib/ # Utilities, Supabase client
│ └── .env.local
└── docs/ # Design documents
├── schema.sql
├── scoping-quiz-generator-v1-v2-LOCKED.md
└── project-workflow-document.md 

## Slice Roadmap (build one at a time, in this order)
- Slice 1: Auth + Tenant setup (Supabase Auth wiring)
- Slice 2: Document upload + storage
- Slice 3: AI quiz generation
- Slice 4: Teacher review interface  
- Slice 5: Student quiz-taking
- Slice 6: Grading + results

Only work on one slice at a time. Don't jump ahead.

## Coding Conventions
- Python: use ruff for linting, black-compatible formatting
- TypeScript: use ESLint + Prettier
- All API responses use Pydantic models (typed)
- All database access via SQLModel, not raw SQL
- All secrets in .env files, never in code

## Testing
- Backend: pytest with real Supabase test project
- Frontend: manual testing during Phase 1 (add unit tests in Phase 2)

## Deployment
- Deploy to Vercel after each slice is complete
- Never deploy broken code to production
- Verify locally first