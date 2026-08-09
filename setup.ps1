# Heartlink one-shot setup for Windows.
# Clones (or updates) the repo, installs dependencies, and starts the app.
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/Theoduras/claude.git"
$Branch = "claude/localhost-login-page-el4mjf"
$TargetDir = Join-Path $HOME "heartlink"

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

Write-Host "Seeding 20 demo members into the live-search pool ..."
& $python seed_demo.py

Write-Host ""
Write-Host "Starting Heartlink at http://localhost:5000 (Ctrl+C to stop)" -ForegroundColor Green
Start-Process "http://localhost:5000"
& $python app.py
