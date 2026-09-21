param([switch]$Restart)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPath = Join-Path $projectRoot 'backend'
$pythonPath = Join-Path $backendPath '.venv\Scripts\python.exe'
$stateFolder = Join-Path $projectRoot '.tmp'
$stateFile = Join-Path $stateFolder 'faculty-worker.json'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Backend virtual environment not found.' }
if (Test-Path -LiteralPath $stateFile) {
    $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    $running = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if ($running -and $running.StartTime.ToUniversalTime().ToString('o') -eq $state.startedAt) {
        if (-not $Restart) {
            Write-Output "Faculty worker is already running (PID $($running.Id))."
            exit 0
        }
        # Restart only our recorded process tree, never the user's API terminal.
        # An interrupted active job is recovered by the database lease policy.
        & taskkill.exe /PID $running.Id /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not stop the recorded worker.' }
    }
}
New-Item -ItemType Directory -Path $stateFolder -Force | Out-Null
$worker = Start-Process -FilePath $pythonPath -ArgumentList '-X','utf8','-u','-m','app.services.faculty_worker' `
    -WorkingDirectory $backendPath -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $stateFolder 'faculty-worker.out.log') `
    -RedirectStandardError (Join-Path $stateFolder 'faculty-worker.err.log')
$startedAt = $worker.StartTime.ToUniversalTime().ToString('o')
Start-Sleep -Seconds 2
$worker.Refresh()
if ($worker.HasExited) { throw 'Worker exited. Check .tmp/faculty-worker.err.log and FACULTY_JOBS_ENABLED.' }
@{pid=$worker.Id; startedAt=$startedAt} | ConvertTo-Json | Set-Content -LiteralPath $stateFile
Write-Output "Faculty worker started (PID $($worker.Id)). Logs: .tmp/faculty-worker.err.log"
