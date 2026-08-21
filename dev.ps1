# Velvet local development launcher.
#
#   powershell -ExecutionPolicy Bypass -File dev.ps1
#
# Deliberately does NOT touch git. The code on disk is the code that runs —
# that is the whole point. Use setup.ps1 for the first-time clone; use this
# every day after that.

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Stamp = Join-Path $VenvDir ".requirements-stamp"

function Fail($msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

# --- .env ---------------------------------------------------------------
# Simple KEY=value parser. Blank lines and # comments are skipped; values are
# taken literally, so don't quote them in .env.
$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
    Write-Host "Loading .env ..."
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $split = $trimmed.IndexOf("=")
        if ($split -lt 1) { continue }
        $key = $trimmed.Substring(0, $split).Trim()
        $value = $trimmed.Substring($split + 1).Trim()
        Set-Item -Path "env:$key" -Value $value
    }
} else {
    Write-Host "No .env found. Copying .env.example ..." -ForegroundColor Yellow
    Copy-Item (Join-Path $Root ".env.example") $EnvFile
    Write-Host "Created .env — re-run dev.ps1." -ForegroundColor Green
    exit 0
}

# --- Postgres -----------------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker not found. Install Docker Desktop (winget install -e --id Docker.DockerDesktop), start it, then re-run."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "Docker is installed but not running. Start Docker Desktop and wait for the whale icon to settle, then re-run."
}

Write-Host "Starting Postgres ..."
docker compose --project-directory $Root up -d
if ($LASTEXITCODE -ne 0) { Fail "docker compose up failed." }

# Wait on the healthcheck rather than the port: the port accepts connections
# a second or so before the database is ready to answer queries.
Write-Host -NoNewline "Waiting for Postgres to accept queries "
$ready = $false
foreach ($attempt in 1..45) {
    $state = (docker inspect -f '{{.State.Health.Status}}' velvet-db 2>$null)
    if ($state -eq "healthy") { $ready = $true; break }
    Write-Host -NoNewline "."
    Start-Sleep -Seconds 1
}
Write-Host ""
if (-not $ready) { Fail "Postgres did not become healthy. Check: docker compose logs db" }

# --- Virtualenv ---------------------------------------------------------
if (-not (Test-Path $VenvPython)) {
    $python = $null
    foreach ($candidate in @("py", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { $python = $candidate; break }
    }
    if (-not $python) {
        Fail "Python not found. Install it (winget install -e --id Python.Python.3.12) and check 'Add python.exe to PATH', then re-run."
    }
    Write-Host "Creating virtualenv in .venv ..."
    & $python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Fail "Failed to create the virtualenv." }
}

# Only reinstall when requirements.txt is newer than the last install. This is
# what keeps the everyday path fast — pip is the slowest step by far.
$Requirements = Join-Path $Root "requirements.txt"
$needsInstall = $true
if (Test-Path $Stamp) {
    $needsInstall = (Get-Item $Requirements).LastWriteTimeUtc -gt (Get-Item $Stamp).LastWriteTimeUtc
}
if ($needsInstall) {
    Write-Host "Installing dependencies ..."
    & $VenvPython -m pip install --quiet --upgrade pip
    & $VenvPython -m pip install --quiet -r $Requirements
    if ($LASTEXITCODE -ne 0) { Fail "pip install failed." }
    New-Item -ItemType File -Path $Stamp -Force | Out-Null
} else {
    Write-Host "Dependencies up to date."
}

# --- Seed ---------------------------------------------------------------
# app.py creates the schema at import time, so this also bootstraps a fresh
# database. seed_demo.py is idempotent; `python seed_demo.py --reset` wipes
# and re-adds the demo members if they drift.
Write-Host "Seeding demo members (idempotent) ..."
Push-Location $Root
try {
    & $VenvPython seed_demo.py
    if ($LASTEXITCODE -ne 0) { Fail "Seeding failed. Check DATABASE_URL in .env." }

    Write-Host ""
    Write-Host "Velvet is starting at http://localhost:5000 (Ctrl+C to stop)" -ForegroundColor Green
    Write-Host "Edit a file, save, refresh the browser — no restart needed." -ForegroundColor Green
    Write-Host ""
    Start-Process "http://localhost:5000"
    & $VenvPython app.py
} finally {
    Pop-Location
}
