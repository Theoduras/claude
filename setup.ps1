# Velvet first-time setup for Windows.
# Clones the repo, installs dependencies, and starts the app.
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File setup.ps1
#
# This is bootstrap only. Once you have a working copy, use dev.ps1 instead —
# it starts the app from the code already on disk without touching git.

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/Theoduras/claude.git"
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
    # Don't touch an existing copy — it may hold uncommitted local work, and
    # pulling over it is exactly the round-trip dev.ps1 exists to avoid.
    Write-Host "Found an existing copy in $TargetDir — leaving it alone."
    Write-Host "Use dev.ps1 in that directory to run it." -ForegroundColor Green
} else {
    Write-Host "Cloning into $TargetDir ..."
    git clone $RepoUrl $TargetDir
}

Write-Host "Installing dependencies ..."
& $python -m pip install --quiet -r (Join-Path $TargetDir "requirements.txt")

Set-Location $TargetDir

# Velvet stores its data in PostgreSQL so it can run across many instances
# in the cloud; there is no local SQLite file any more. docker-compose.yml
# provides one locally, and dev.ps1 starts it, waits for it, seeds it, and
# runs the app — so hand off rather than duplicating any of that here.
Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "From now on, run the app with:"
Write-Host "  cd $TargetDir"
Write-Host "  .\dev.ps1"
Write-Host ""
Write-Host "dev.ps1 needs Docker Desktop running (it hosts Postgres):"
Write-Host "  winget install -e --id Docker.DockerDesktop"
Write-Host ""
Write-Host "See docs/deploy-gcp.md for the cloud deployment." -ForegroundColor DarkGray
