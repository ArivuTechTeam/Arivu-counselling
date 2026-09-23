# Supervise the faculty worker: run it in the foreground and automatically
# restart it if it exits (crash, transient DB/provider failure, etc.), so a died
# worker does not silently leave jobs stuck in 'queued'. Ctrl+C stops the loop.
#
# This is additive dev/ops tooling and does not replace start-faculty-worker.ps1
# (which launches a single detached worker). For production, run the worker as a
# managed service with the platform's own restart policy.
param([double]$BackoffSeconds = 3)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPath = Join-Path $projectRoot 'backend'
$pythonPath = Join-Path $backendPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Backend virtual environment not found.' }

Write-Output "Supervising faculty worker (restart backoff ${BackoffSeconds}s). Press Ctrl+C to stop."
$restarts = 0
while ($true) {
    $startedAt = Get-Date
    try {
        & $pythonPath -X utf8 -u -m app.services.faculty_worker
    } catch {
        Write-Warning "Worker raised: $($_.Exception.Message)"
    }
    $ranFor = [int]((Get-Date) - $startedAt).TotalSeconds
    $restarts++
    Write-Warning "Faculty worker exited after ${ranFor}s (restart #$restarts). Restarting in ${BackoffSeconds}s..."
    if ($ranFor -lt 5) {
        # Exiting immediately usually means a config problem (e.g. FACULTY_JOBS_ENABLED
        # unset) or a missing dependency — don't hot-loop; back off harder.
        Write-Warning "Worker exited almost immediately; check .env FACULTY_JOBS_ENABLED and the worker logs."
        Start-Sleep -Seconds ([Math]::Max($BackoffSeconds, 10))
    } else {
        Start-Sleep -Seconds $BackoffSeconds
    }
}
