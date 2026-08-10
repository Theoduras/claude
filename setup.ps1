# Velvet one-shot setup for Windows.
# Clones (or updates) the repo, installs dependencies, and starts the app.
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/Theoduras/claude.git"
$Branch = "claude/determined-wozniak-orobzv"
$TargetDir = Join-Path $HOME "velvet"
$LegacyDir = Join-Path $HOME "heartlink"

function Fail($msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

# Find Python (py launcher first, then python)
$python = $null
foreach ($candidate in @("py", "python")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $python = $candidate
        break
    }
}
if (-not $python) {
    Fail "Python not found. Install it from https://www.python.org/downloads/ and check 'Add python.exe to PATH', then re-run this script."
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "Git not found. Install it from https://git-scm.com/download/win, then re-run this script."
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

Write-Host "Installing dependencies ..."
& $python -m pip install --quiet -r (Join-Path $TargetDir "requirements.txt")

Set-Location $TargetDir

# Velvet stores its data in PostgreSQL so it can run across many instances
# in the cloud; there is no local SQLite file any more.
if (-not $env:DATABASE_URL) {
    Write-Host ""
    Write-Host "DATABASE_URL is not set." -ForegroundColor Yellow
    Write-Host "Velvet needs a PostgreSQL database. With Docker installed:"
    Write-Host ""
    Write-Host '  docker run -d --name velvet-pg -e POSTGRES_PASSWORD=postgres `'
    Write-Host '    -e POSTGRES_DB=velvet -p 5432:5432 postgres:16'
    Write-Host '  $env:DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/velvet"'
    Write-Host ""
    Write-Host "Then re-run this script. See docs/deploy-gcp.md for details."
    exit 1
}

Write-Host "Seeding 20 demo members into the live-search pool ..."
& $python seed_demo.py

Write-Host ""
Write-Host "Starting Velvet at http://localhost:5000 (Ctrl+C to stop)" -ForegroundColor Green
Start-Process "http://localhost:5000"
& $python app.py
