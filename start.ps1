# One-command local start (Windows PowerShell).
#   .\start.ps1            normal start
#   .\start.ps1 sandbox    + FAKE Teams/Zoom/Google Meet server to try the integrations (dev/test only)
#   .\start.ps1 stop
param([string]$Action = "start")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$files = @("-f", "docker-compose.yml")
if ($Action -eq "sandbox" -or $Action -eq "stop") { $files += @("-f", "docker-compose.sandbox.yml") }

if ($Action -eq "stop") { docker compose @files down --remove-orphans; exit 0 }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Host "Chua cai Docker. Cai Docker Desktop: https://www.docker.com/products/docker-desktop/"; exit 1
}
docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "Docker chua chay. Hay mo Docker Desktop roi chay lai."; exit 1 }

if (-not (Test-Path .env)) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $key = [Convert]::ToBase64String($bytes)
  (Get-Content .env.example) -replace '^SECRET_ENCRYPTION_KEYS=.*', "SECRET_ENCRYPTION_KEYS=kdev:$key" | Set-Content .env -Encoding utf8
  Write-Host "Da tao file .env (kem khoa ma hoa)"
}

Write-Host "Dang build va khoi dong (lan dau co the mat 3-10 phut)..."
docker compose @files up --build -d
if ($LASTEXITCODE -ne 0) { Write-Host "Loi khi khoi dong. Xem: docker compose logs --tail=50"; exit 1 }

Write-Host "Cho ung dung san sang..."
for ($i = 0; $i -lt 120; $i++) {
  try {
    Invoke-WebRequest -UseBasicParsing http://localhost:3000/login -TimeoutSec 3 | Out-Null
    Write-Host "San sang: http://localhost:3000  (dang nhap: Tran Minh (PM) - pm@example.com)"
    if ($Action -eq "sandbox") {
      Write-Host "SANDBOX: Teams/Zoom/Google Meet la may chu GIA LAP (localhost:9100). Vao 'Tich hop nen tang' de thu."
      Write-Host "Huong dan: docs/integrations/sandbox-vi.md"
    }
    Start-Process "http://localhost:3000"
    exit 0
  } catch { Start-Sleep -Seconds 3 }
}
Write-Host "Het thoi gian cho. Xem log: docker compose logs --tail=50"; exit 1
