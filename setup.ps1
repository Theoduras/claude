# Velvet one-shot setup for Windows.
# Clones (or updates) the repo, starts Postgres in Docker, installs
# dependencies, seeds demo data, and starts the app.
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/Theoduras/claude.git"
$Branch = "claude/localhost-login-page-el4mjf"
$TargetDir = Join-Path $HOME "velvet"
$LegacyDir = Join-Path $HOME "heartlink"

function Fail($msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

function Have($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

# Find Python (py launcher first, then python)
$python = $null
foreach ($candidate in @("py", "python")) {
    if (Have $candidate) { $python = $candidate; break }
}
if (-not $python) {
    Fail "Python not found. Install it from https://www.python.org/downloads/ and check 'Add python.exe to PATH', then re-run this script."
}

if (-not (Have "git")) {
    Fail "Git not found. Install it from https://git-scm.com/download/win, then re-run this script."
}

if (-not (Have "docker")) {
    Fail "Docker not found. Velvet stores its data in PostgreSQL, which this script runs in a container. Install Docker Desktop from https://www.docker.com/products/docker-desktop/, start it, then re-run this script."
}

# Docker Compose v2 is a subcommand; older standalone docker-compose still works.
$composeCmd = @("docker", "compose")
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    if (Have "docker-compose") {
        $composeCmd = @("docker-compose")
    } else {
        Fail "Docker is installed but Docker Compose is not available. Update Docker Desktop, then re-run this script."
    }
}

function Compose {
    $exe = $composeCmd[0]
    $pre = @($composeCmd[1..($composeCmd.Length - 1)])
    & $exe @($pre + $args)
}

# Docker Desktop's engine can take a while after login; fail with a clear
# message rather than a wall of socket errors from compose.
& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "Docker is installed but its engine isn't running. Start Docker Desktop, wait for it to say 'Engine running', then re-run this script."
}

# The project used to clone into ~\heartlink; carry that copy over so the
# existing database and any local edits move with the rename.
if ((Test-Path (Join-Path $LegacyDir ".git")) -and -not (Test-Path $TargetDir)) {
    Write-Host "Renaming $LegacyDir to $TargetDir ..."
    Rename-Item -Path $LegacyDir -NewName "velvet"
}

if (Test-Path (Join-Path $TargetDir ".git")) {
    Write-Host "Updating existing copy in $TargetDir ..."
    git -C $TargetDir fetch origin $Branch
    git -C $TargetDir checkout $Branch
    git -C $TargetDir pull origin $Branch
} else {
    Write-Host "Cloning into $TargetDir ..."
    git clone -b $Branch $RepoUrl $TargetDir
}

Set-Location $TargetDir

Write-Host "Installing dependencies ..."
& $python -m pip install --quiet -r requirements.txt

Write-Host "Starting PostgreSQL in Docker ..."
Compose up -d
if ($LASTEXITCODE -ne 0) {
    Fail "Could not start PostgreSQL. If something else is already using port 5432, stop it (or change the port mapping in docker-compose.yml) and re-run this script."
}

# The app's connection pool gives up after 30s, so seeding a database that is
# still starting fails. Wait for the container's own healthcheck instead.
Write-Host "Waiting for PostgreSQL to accept connections ..." -NoNewline
$healthy = $false
foreach ($i in 1..60) {
    $status = (& docker inspect -f '{{.State.Health.Status}}' velvet-db 2>$null)
    if ($status -eq "healthy") { $healthy = $true; break }
    Start-Sleep -Seconds 2
    Write-Host "." -NoNewline
}
Write-Host ""
if (-not $healthy) {
    Fail "PostgreSQL did not become ready in time. Check 'docker compose logs db' for details."
}

Write-Host "Seeding 20 demo members into the live-search pool ..."
& $python seed_demo.py

Write-Host ""
Write-Host "Starting Velvet at http://localhost:5000 (Ctrl+C to stop)" -ForegroundColor Green
Write-Host "The database keeps running in Docker. Stop it with: docker compose down" -ForegroundColor DarkGray
Start-Process "http://localhost:5000"
& $python app.py
