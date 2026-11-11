# Отправка обновления на GitHub.
# Запуск: powershell -ExecutionPolicy Bypass -File scripts\push.ps1
Set-Location (Split-Path $PSScriptRoot -Parent)

# секреты и база не должны попасть в git
$secret = git ls-files .env data
if ($secret) {
    Write-Host "STOP: в git лежат секреты: $secret" -ForegroundColor Red
    Write-Host "Выполните: git rm --cached -r .env data   и запустите снова"
    exit 1
}

# .gitignore: секреты, база, бэкапы, файл фирменных моделей (его пишет админка на сервере)
$ignore = @(".env", "data/", "backups/", "config/branded.yml", "config/*.bak", ".venv/", "__pycache__/")
$cur = if (Test-Path .gitignore) { Get-Content .gitignore } else { @() }
$add = $ignore | Where-Object { $cur -notcontains $_ }
if ($add) { Add-Content .gitignore $add; Write-Host "[OK] .gitignore: + $($add -join ', ')" }

# проверка, что новый бэкенд действительно на месте
if (-not (Select-String -Quiet -Path app\core\catalog.py -Pattern "save_branded")) {
    Write-Host "STOP: в app\core\catalog.py нет новых правок" -ForegroundColor Red
    exit 1
}

git add app web scripts .gitignore
git status --short
git commit -m "update backend + web"
git push origin main
if ($LASTEXITCODE -eq 0) { Write-Host "`n[OK] Отправлено. Теперь на сервере: bash /root/update.sh" -ForegroundColor Green }
