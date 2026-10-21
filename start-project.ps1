param([switch]$CheckOnly, [switch]$Stop)
$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot 'bilibili-ai-bot'
$dataDir = Join-Path $project 'data'
$logDir = Join-Path $dataDir 'launcher-logs'
$stateFile = Join-Path $dataDir 'launcher.json'
$url = 'http://127.0.0.1:5000'
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$state = @{}
$mutex = $null
$locked = $false

function Save-State {
    $state | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
}

function Get-OwnedProcess($name) {
    if (-not $state.ContainsKey($name)) { return $null }
    $entry = $state[$name]
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.pid)" -ErrorAction SilentlyContinue
    $expected = Join-Path $project $entry.script
    if ($process -and $process.CommandLine -and $process.CommandLine.Contains('"' + $expected + '"')) {
        return $process
    }
    return $null
}

function Start-ServiceProcess($name, $script) {
    if (Get-OwnedProcess $name) {
        Write-Host "$name is already running."
        return
    }
    $scriptPath = Join-Path $project $script
    $process = Start-Process -FilePath $python -ArgumentList @('-X', 'utf8', '-u', ('"' + $scriptPath + '"')) `
        -WorkingDirectory $project -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir "$name.log") `
        -RedirectStandardError (Join-Path $logDir "$name-error.log")
    $state[$name] = @{ pid = $process.Id; script = $script }
    Save-State
    Write-Host "Started $name (PID $($process.Id))."
}

try {
    # Serialize double-clicks, so two launchers cannot create duplicate bots.
    $hash = [System.Security.Cryptography.SHA256]::Create()
    $id = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($project.ToLowerInvariant()))).Replace('-', '')
    $hash.Dispose()
    $mutex = New-Object System.Threading.Mutex($false, "Local\BiliBotLauncher-$id")
    try { $locked = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { Write-Host 'Another launcher is already working.'; exit 0 }
    if (Test-Path -LiteralPath $stateFile) {
        $saved = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($property in $saved.PSObject.Properties) { $state[$property.Name] = $property.Value }
    }
    if ($Stop) {
        foreach ($name in @('bot', 'web')) {
            $process = Get-OwnedProcess $name
            if ($process) {
                # Terminate the owned process tree, including active video workers.
                & taskkill.exe /PID $process.ProcessId /T /F
                if ($LASTEXITCODE -ne 0) { throw "Could not stop $name." }
            }
            $state.Remove($name)
        }
        if (Test-Path -LiteralPath $dataDir) { Save-State }
        Write-Host 'Project stopped.'
        exit 0
    }
    if (-not (Test-Path -LiteralPath (Join-Path $project 'ai.py'))) { throw "Project missing: $project" }
    $venvPython = Join-Path $project '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) { $python = $venvPython }
    else { $python = (Get-Command python.exe -ErrorAction Stop).Source }
    foreach ($tool in @('ffmpeg.exe', 'ffprobe.exe', 'yt-dlp.exe')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing tool: $tool" }
    }
    & $python -X utf8 -c 'import flask, openai, requests, lunardate, cryptography, qrcode'
    if ($LASTEXITCODE -ne 0) { throw 'Python dependencies missing. Install bilibili-ai-bot/Requirements.txt first.' }
    if ($CheckOnly) { Write-Host 'PASS: Python, dependencies, FFmpeg, ffprobe and yt-dlp are available. No services started.'; exit 0 }
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    # Do not start a second copy of scripts already launched by this tool.
    # Refuse to reuse a port belonging to some other application.
    $listeners = @(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue)
    $web = Get-OwnedProcess 'web'
    if ($listeners.Count -gt 0 -and (-not $web -or @($listeners | Where-Object OwningProcess -ne $web.ProcessId).Count -gt 0)) {
        throw 'Port 5000 is in use by an unmanaged process. Stop the old Web panel/application and try again.'
    }
    Start-ServiceProcess 'web' 'local-chat.py'
    Write-Host 'Waiting for Web panel...'
    $ready = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        if (-not (Get-OwnedProcess 'web')) { throw "Web panel exited. Check $logDir\web-error.log" }
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "Web panel did not become ready. Check $logDir" }
    Start-ServiceProcess 'bot' 'ai.py'
    Start-Sleep -Seconds 2
    if (-not (Get-OwnedProcess 'bot')) { throw "Bot exited. Check $logDir\bot-error.log" }
    Start-Process $url
    Write-Host "Ready: $url"
    Write-Host "Logs: $logDir"
    Write-Host 'Services run in the background. Use the stop launcher to stop them.'
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "Logs (if created): $logDir"
    exit 1
} finally {
    if ($locked -and $mutex) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
