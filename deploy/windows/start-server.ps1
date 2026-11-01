# Run the M7 server on THIS Windows PC (single-machine test mode, before M7 exists).
# From the repo root, in a normal (non-admin) PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\deploy\windows\start-server.ps1              # local runners (Git Bash shell, your installed claude)
#   .\deploy\windows\start-server.ps1 -WithDocker  # sandbox + Jarvis in Docker Desktop containers instead
# Safe to re-run. Ctrl+C stops the server. Data lives in .\data (git-ignored).
param([switch]$WithDocker)
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Repo
$py = Join-Path $Repo ".venv\Scripts\python.exe"

Write-Host "== Python environment ==" -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Install Python 3.11+ from python.org (tick 'Add to PATH')." }
if (-not (Test-Path $py)) { python -m venv .venv }
& $py -m pip install -q --upgrade pip
& $py -m pip install -q -e .

Write-Host "== Config ==" -ForegroundColor Cyan
if (-not (Test-Path config\settings.yaml)) {
    $initArgs = @("-m", "assistant", "init", "--local")
    if ($WithDocker) { $initArgs += "--docker" }
    & $py @initArgs
} else {
    Write-Host "Using existing config\settings.yaml (delete it to regenerate local test settings)."
}
if (Test-Path pc\config.yaml) { & $py -m assistant pair-pc }    # share tokens with the PC side on this machine
else { Write-Host "No pc\config.yaml yet: run pc\install.ps1 -M7Ip 127.0.0.1 (admin) for voice + PC control." -ForegroundColor Yellow }

if ($WithDocker) {
    Write-Host "== Docker sandbox ==" -ForegroundColor Cyan
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker Desktop not found. Install it, or run without -WithDocker." }
    docker build -t pa-sandbox:latest sandbox
    $env:VAULT = Join-Path $Repo "data"          # same layout as M7's /mnt/vault
    docker compose -f deploy\m7\docker-compose.yml up -d sandbox
    Write-Host "Log Claude Code in for Jarvis once:  docker exec -it pa-sandbox claude"
}

Write-Host "== Checks ==" -ForegroundColor Cyan
& $py -m assistant doctor

$token = ((Get-Content .env) | Where-Object { $_ -like "ASSISTANT_API_TOKEN=*" }) -replace "ASSISTANT_API_TOKEN=", ""
Write-Host ""
Write-Host "Web app:  http://localhost:8000/app?token=$token" -ForegroundColor Green
Write-Host "Terminal: .venv\Scripts\python.exe -m assistant chat   (in another window)" -ForegroundColor Green
Write-Host ""
& $py -m assistant serve
