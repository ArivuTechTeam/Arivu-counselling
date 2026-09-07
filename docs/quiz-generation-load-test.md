# Quiz generation concurrency check

Run the repeatable check from `backend/`:

```bash
venv/bin/python -m pytest -s tests/test_quiz_generation_load.py
```

## Result (2026-09-07)

The test sent 15 simultaneous HTTP `POST` requests to the real
`/api/v1/quiz-sets/generate` FastAPI route through one local Uvicorn server.
All 15 returned HTTP 200. The server reached 15 concurrent route handlers,
finished the batch in 0.298 seconds, and the slowest request took 0.121 seconds.

The paid AI and database generation function is stubbed with a short delay, and
authentication is replaced with a test teacher. The P0 rate-limit call is also
stubbed when that branch is present because its counter behavior is tested
separately. This keeps the check repeatable and prevents test runs from creating
quiz records or consuming Gemini/DeepSeek quota.

This proves that the API route itself does not serialize or reject a burst of 15
requests. It does not measure Gemini/DeepSeek quota, Supabase latency, or the CPU
and memory available to the Railway production instance. A credentialed staging
run is still needed to measure those external limits safely; do not point this
test at production.

Student quiz starts do not call this AI generation route. This route is a
teacher-only content-creation action, so a class of students starting an already
published quiz exercises the student attempt endpoints instead.
