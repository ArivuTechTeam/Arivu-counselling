# Local generation timeout fix

The synchronous generation client used to abort after 90 seconds, even though one
provider call could wait 120 seconds and generation includes verification/repair.
The connection-error wording did not establish that the network was at fault.

Local development uses `backend/.env`. Enable `FACULTY_JOBS_ENABLED=true` after
migration 43, and run the API and a separate worker with the same environment.
Generation then submits a durable job and returns promptly; its completion is
visible under Recent tasks. The browser no longer waits for the whole AI pipeline.

From the project root in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-faculty-worker.ps1
```

This starts a hidden worker, records its PID/start time under `.tmp`, and avoids
starting a duplicate through the same launcher. Its logs are in
`.tmp/faculty-worker.err.log`. After changing worker code/settings, use `-Restart`.
Prefer doing so when jobs are idle; an interrupted job resumes under the lease
recovery policy and may repeat provider work before its checkpoint.

Restart your existing backend terminal after changing `.env`; configuration is
cached for the running process. Keep your original port and launch command. For
development frontend servers, refresh the page; production frontend servers need
a rebuild/restart. After reboot, run the worker launcher again.

For older installations with background jobs disabled, both synchronous generation
routes now allow 15 minutes. This is a compatibility fallback, not a promise that
any arbitrary document will finish in that time. A true timeout directs faculty
to check Recent tasks/Review queue before submitting again; synchronous POSTs are
not automatically repeated.

Image/diagram-aware generation remains deferred to Phase 2. The timeout handling
and background worker are independent of that future media work.

Regression check: `node scripts/test-generation-timeouts.mjs` exercises both real
frontend API functions with a virtual clock, confirms a response after 90 seconds
is accepted, checks final timeout guidance and verifies queued retries preserve
their idempotency key.
