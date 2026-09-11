# Four-role reliability audit — 11 Sep 2026

Scope: phases 1–5 of the production reliability plan. AI generation,
extraction, regeneration, and explanation endpoints were explicitly excluded.

## Outcome

- **Confirmed:** All 77 local API journey checks passed across super admin,
  institution admin, teacher, student, authentication, role boundaries, and
  tenant boundaries. Expected results were 68 HTTP 200, two 400, two 401,
  three 403, and two 404 responses.
- **Confirmed:** All 27 static live dashboard routes returned HTTP 200 from
  Vercel.
- **Confirmed:** The staged live mixed-role test completed 1,005 requests with
  no failures through 150 concurrent workers. At that stage it sustained 32.8
  requests/second with 5.026-second p95 latency.
- **Confirmed:** A 330.968-second live soak completed 3,375 requests. Two reads
  timed out in its final round: `/api/v1/exam/config` and `/api/v1/daily`.
  The overall observed failure rate was 0.059%; worst completed-round p95 was
  5.391 seconds.
- **Confirmed:** No AI endpoint was called by any audit or load harness.
- **Confirmed:** Final verification passed 129 backend tests and 88 subtests,
  frontend lint with no warnings, and the 36-route production build.

## Phase 1 — Traceable errors

Every frontend API request now carries a safe request ID. The backend returns
that ID in `X-Request-ID`, includes it in controlled 500/503 bodies, and logs
method, path, status, and elapsed time. Unsafe client-supplied IDs are replaced
so they cannot forge log lines. CORS exposes `X-Request-ID` and `Retry-After`
to the browser.

The frontend now classifies authentication, permission, missing-data,
conflict, rate-limit, unavailable-service, server, network, cancellation, and
timeout failures. User-visible transient errors include the request reference
needed to locate the matching backend log.

## Phase 2 — Four-role functional audit

The audit created two isolated temporary tenants and exercised:

- super-admin platform stats, overview, question bank, AI-monitoring metadata,
  tenant, administrator, and course reads;
- institution-admin dashboard/analytics reads plus course, subject, and
  teacher-assignment CRUD;
- teacher dashboard/monitoring/content reads plus chapter CRUD;
- student dashboard, quiz history, revision, bookmarks, leaderboard, daily,
  exam, Smart Quiz, and challenge reads.

The student journey also completed quiz start, autosave, refresh, partial
submission rejection, deterministic grading, double-submission rejection,
bookmarking, Smart Quiz, Daily Challenge, Exam Simulator, and a two-player
Challenge a Friend flow. The known-answer quiz returned the expected 9/10.

## Phase 3 — Security and tenant isolation

**Confirmed:** malformed and expired tokens returned 401; student-to-admin and
teacher-to-super-admin requests returned 403; another tenant could not read an
attempt, challenge, or subject chapters; repeated and incomplete submissions
were rejected. The focused regression suite passed 84 tests and 40 subtests.

## Phase 4 — Live load and soak

| Concurrent workers | Requests | Errors | Throughput | p95 |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 30 | 0 | 3.64 req/s | 3.730 s |
| 25 | 75 | 0 | 8.95 req/s | 2.551 s |
| 50 | 150 | 0 | 22.76 req/s | 2.587 s |
| 100 | 300 | 0 | 29.95 req/s | 3.804 s |
| 150 | 450 | 0 | 32.80 req/s | 5.026 s |

The follow-up soak used 25 concurrent mixed-role workers for 45 rounds. Most
rounds held near 2.2–2.8-second p95. Two isolated rounds rose to 4.827 and
5.391 seconds and recovered immediately. The final round contained the two
30-second client timeouts described above.

## Phase 5 — Failure diagnosis and hardening

### High — frontend/backend timeout mismatch

- **Confirmed:** normal frontend requests stop after 20 seconds, but a single
  Supabase read previously waited 30 seconds before the backend transport
  attempted its first retry.
- **Probable root cause:** the two simultaneous soak failures were stalled data
  reads that the browser/load client abandoned before backend recovery could
  begin. Railway recorded no corresponding application warning or HTTP error,
  so provider-side proof for those exact requests was unavailable.
- **Fix:** Supabase read-attempt timeout is now configurable with
  `SUPABASE_READ_TIMEOUT_SECONDS` and defaults to five seconds. Three bounded
  backend attempts can therefore complete before the ordinary frontend
  deadline. Writes keep their existing timeout and are never retried.
- **Fix:** the frontend retries one time only for idempotent GET transport
  failures and HTTP 502/503/504 responses, within the original 20-second total
  deadline. Starts, submissions, autosaves, and other writes are not replayed.

### Medium — untraceable generic errors

- **Confirmed:** the deployed version used during the load test did not echo
  client request IDs, making an isolated browser error difficult to match to a
  server request.
- **Fix:** request IDs and typed, retry-aware frontend errors were added as
  described in Phase 1. Controlled 500 and 503 checks confirmed that internal
  exception text is not returned to the browser and 503 includes
  `Retry-After: 2`.

## Verification boundary

- **Confirmed locally:** request-ID propagation, CORS, safe/unsafe request-ID
  handling, controlled 500/503 contracts, focused backend regressions, and the
  four-role API journeys.
- **Confirmed live before this branch is deployed:** route availability,
  staged concurrency results, and the five-minute soak result.
- **Pending:** repeat the live soak after this branch is merged and both
  Railway and Vercel are redeployed. Repository tests cannot prove those
  deployment states.
- **Limitation:** this environment has no browser automation runtime, so a real
  four-account Chrome Console/Network click-through was not claimed. API
  journeys, live route responses, TypeScript checks, and the production build
  cover the automated portion.
