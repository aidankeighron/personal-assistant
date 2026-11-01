# Windows PC setup for the assistant. Run in an *elevated* PowerShell from the repo's pc\ folder:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\install.ps1 -M7Ip 100.x.y.z            # M7's Tailscale (or LAN) IP
#   .\install.ps1 -M7Ip 127.0.0.1            # testing with the server on this same PC (deploy\windows\start-server.ps1)
# Optional: -SkipModels  -NoAutostart
param(
    [Parameter(Mandatory = $true)][string]$M7Ip,
    [switch]$SkipModels,
    [switch]$NoAutostart
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

Write-Host "== Python venv ==" -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Install Python 3.11+ from python.org first (tick 'Add to PATH')." }
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -q

if (-not (Test-Path config.yaml)) {
    Copy-Item config.example.yaml config.yaml
    $tok = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
    (Get-Content config.yaml) -replace '  token: change-me', "  token: $tok" | Set-Content config.yaml
    if ($M7Ip -in @("127.0.0.1", "localhost")) {   # single-machine test mode: the server runs on this PC
        (Get-Content config.yaml) -replace '  url: http://m7:8000', '  url: http://localhost:8000' | Set-Content config.yaml
        Write-Host "Same-machine mode: server.url = http://localhost:8000. Run 'python -m assistant pair-pc' in the repo to share tokens." -ForegroundColor Yellow
    }
    Write-Host "Created pc\config.yaml. host_agent.token = $tok  -> put this in M7 .env as PC_HOST_TOKEN" -ForegroundColor Yellow
}

Write-Host "== Ollama settings (keeps VRAM free when idle) ==" -ForegroundColor Cyan
$ollamaEnv = @{ OLLAMA_HOST = "0.0.0.0"; OLLAMA_KEEP_ALIVE = "2m"; OLLAMA_MAX_LOADED_MODELS = "1";
               OLLAMA_NUM_PARALLEL = "1"; OLLAMA_FLASH_ATTENTION = "1" }
foreach ($k in $ollamaEnv.Keys) {
    [Environment]::SetEnvironmentVariable($k, $ollamaEnv[$k], "User")   # future logons
    Set-Item -Path "Env:$k" -Value $ollamaEnv[$k]                         # the Ollama we restart below
}
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama not found. Install from https://ollama.com/download, then re-run." -ForegroundColor Yellow
} else {
    Write-Host "Restarting Ollama so it picks up the new settings..."
    Get-Process ollama*, "ollama app" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep 2
    $tray = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
    if (Test-Path $tray) { Start-Process $tray } else { Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden }
    for ($i = 0; $i -lt 20; $i++) {
        try { Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 1 }
    }
}

Write-Host "== Firewall: only M7 may reach Ollama (11434) and the host agent (8090) ==" -ForegroundColor Cyan
foreach ($p in @(11434, 8090)) {
    $name = "Assistant-M7-$p"
    Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $p -RemoteAddress $M7Ip -Action Allow | Out-Null
}

if (-not $SkipModels) {
    Write-Host "== Downloading models (Piper voices, Whisper, Ollama models M7 needs) ==" -ForegroundColor Cyan
    # Idempotent: only fetches what's missing. M7 also auto-pulls Ollama models every 6h.
    & .\.venv\Scripts\python.exe download_models.py
    if ($LASTEXITCODE -ne 0) { Write-Host "Some downloads failed; re-run: .\.venv\Scripts\python.exe download_models.py" -ForegroundColor Yellow }
}

if (-not $NoAutostart) {
    Write-Host "== Autostart at logon ==" -ForegroundColor Cyan
    $py = Join-Path $Here ".venv\Scripts\pythonw.exe"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
    $a1 = New-ScheduledTaskAction -Execute $py -Argument "host_agent.py" -WorkingDirectory $Here
    Register-ScheduledTask -TaskName "Assistant Host Agent" -Action $a1 -Trigger $trigger -Settings $settings -Force | Out-Null
    $a2 = New-ScheduledTaskAction -Execute $py -Argument "voice_client.py" -WorkingDirectory $Here
    Register-ScheduledTask -TaskName "Assistant Voice" -Action $a2 -Trigger $trigger -Settings $settings -Force | Out-Null
    # Weekly re-check so new voices / models added to the configs get fetched without you doing anything
    $weekly = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 4am
    $a3 = New-ScheduledTaskAction -Execute $py -Argument "download_models.py" -WorkingDirectory $Here
    Register-ScheduledTask -TaskName "Assistant Model Updates" -Action $a3 -Trigger $weekly -Settings $settings -Force | Out-Null
    Write-Host "Registered 'Assistant Host Agent', 'Assistant Voice' and 'Assistant Model Updates' (Task Scheduler)."
}

Write-Host ""
Write-Host "Done. Next:" -ForegroundColor Green
Write-Host "  1. Edit pc\config.yaml: server.url / server.api_token, your display profiles and apps."
Write-Host "     (then re-run download_models.py so the Ollama list comes from M7)"
Write-Host "  2. Test:  .\.venv\Scripts\python.exe host_agent.py     (then from M7: python -m assistant doctor)"
Write-Host "  3. Test:  .\.venv\Scripts\python.exe voice_client.py --text"
Write-Host "  4. For the nightly run: enable Wake-on-LAN in BIOS + network adapter properties, put the MAC in M7 .env (PC_MAC)."
