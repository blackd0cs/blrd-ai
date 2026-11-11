# Deploys update to GitHub. Run: powershell -ExecutionPolicy Bypass -File scripts\setup_and_push.ps1
Set-Location $PSScriptRoot\..

# ── 1. Find or install Git ─────────────────────────────────
function Find-Git {
    $paths = @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe",
        "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe",
        "$env:ProgramFiles\Git\bin\git.exe"
    )
    foreach ($p in $paths) { if (Test-Path $p) { return $p } }
    return $null
}

$git = Find-Git
if (-not $git) {
    Write-Host "Git not found. Installing via winget..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("PATH","User")
        $git = Find-Git
    }
    if (-not $git) {
        Write-Host ""
        Write-Host "Auto-install failed. Do it manually:" -ForegroundColor Red
        Write-Host "  1. Open https://git-scm.com/download/win" -ForegroundColor Cyan
        Write-Host "  2. Download 64-bit Setup, install with defaults" -ForegroundColor Cyan
        Write-Host "  3. Close this PowerShell, open a new one" -ForegroundColor Cyan
        Write-Host "  4. Run this script again" -ForegroundColor Cyan
        exit 1
    }
    Write-Host "[OK] Git installed: $git" -ForegroundColor Green
} else {
    Write-Host "[OK] Git found: $git" -ForegroundColor Green
}

$gitDir = Split-Path $git
if ($env:PATH -notlike "*$gitDir*") {
    $env:PATH = "$gitDir;$env:PATH"
}

# ── 2. .gitignore ──────────────────────────────────────────
$ignore = @(".env", "data/", "backups/", "config/branded.yml",
            "config/*.bak", ".venv/", "__pycache__/", "*.pyc",
            "app/data/")
$cur = if (Test-Path .gitignore) { Get-Content .gitignore } else { @() }
$add = $ignore | Where-Object { $cur -notcontains $_ }
if ($add) {
    Add-Content .gitignore $add
    Write-Host "[OK] .gitignore updated: $($add -join ', ')" -ForegroundColor Green
}

# ── 3. Check for tracked secrets ──────────────────────────
$tracked = & $git ls-files .env data app/data 2>$null
if ($tracked) {
    Write-Host ""
    Write-Host "[STOP] Secrets tracked in git: $tracked" -ForegroundColor Red
    Write-Host "Run this in terminal:" -ForegroundColor Yellow
    Write-Host "  git rm --cached -r .env data" -ForegroundColor Cyan
    Write-Host "  Then run this script again" -ForegroundColor Cyan
    exit 1
}

# ── 4. Verify new backend is present ──────────────────────
if (-not (Select-String -Quiet -Path app\core\catalog.py -Pattern "save_branded")) {
    Write-Host ""
    Write-Host "[STOP] app\core\catalog.py missing new code (save_branded)" -ForegroundColor Red
    Write-Host "Make sure all changes are applied" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] New backend present" -ForegroundColor Green

# ── 5. Git config ─────────────────────────────────────────
$name  = & $git config --global user.name  2>$null
$email = & $git config --global user.email 2>$null
if (-not $name) {
    & $git config --global user.name  "blrd deploy"
    & $git config --global user.email "deploy@blrdai.local"
    Write-Host "[OK] Git user configured" -ForegroundColor Green
}

# ── 6. Commit and push ────────────────────────────────────
Write-Host ""
Write-Host "Changed files:" -ForegroundColor Cyan
& $git status --short

& $git add app web scripts .gitignore
$changed = & $git diff --cached --name-only
if (-not $changed) {
    Write-Host ""
    Write-Host "[OK] Nothing to commit - GitHub is up to date" -ForegroundColor Green
    Write-Host "If server still has old code, just run:" -ForegroundColor Yellow
    Write-Host "  bash /root/update.sh" -ForegroundColor Cyan
    exit 0
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
& $git commit -m "update: backend + web [$stamp]"
& $git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] Pushed to GitHub" -ForegroundColor Green
    Write-Host ""
    Write-Host "Now on server:" -ForegroundColor Cyan
    Write-Host "  ssh root@89.144.34.253 'bash /root/update.sh'" -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "[FAIL] Push failed. Possible reasons:" -ForegroundColor Red
    Write-Host "  1. No internet - check connection" -ForegroundColor Yellow
    Write-Host "  2. Private repo - run: git config --global credential.helper manager" -ForegroundColor Yellow
    Write-Host "     then: git push origin main  (login window will open)" -ForegroundColor Yellow
    exit 1
}
