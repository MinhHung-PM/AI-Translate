# Company-network site (Windows PowerShell): HTTPS on this computer's LAN IP, no sign-in,
# AI keys stored on this server only. See docs/deploy-lan-vi.md.
#   .\start-lan.ps1                 start (first run asks for the OpenAI / Soniox keys)
#   .\start-lan.ps1 start 10.0.1.23 use this IP instead of the detected one
#   .\start-lan.ps1 stop            stop the site (data is kept)
#   .\start-lan.ps1 backup          save a database backup into .\backups
param([string]$Action = "start", [string]$Ip = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$EnvFile = ".env.lan"
$Compose = @("compose", "-p", "memohub-lan", "--env-file", $EnvFile, "-f", "docker-compose.yml", "--profile", "lan")

function Write-Utf8Lf([string]$Path, [string]$Text) {
  # LF line endings, no BOM: Docker Compose reads a Windows CRLF as part of each value.
  [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot $Path), ($Text -replace "`r", ""), (New-Object System.Text.UTF8Encoding($false)))
}
function New-Secret([int]$Bytes) {
  $b = New-Object byte[] $Bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  return $b
}
function Read-Key([string]$Prompt) {
  $sec = Read-Host $Prompt -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
  try { return ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)).Trim() } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host "Chua cai Docker Desktop: https://www.docker.com/products/docker-desktop/"; exit 1 }
docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "Docker chua chay. Hay mo Docker Desktop roi chay lai."; exit 1 }

if ($Action -eq "stop") {
  if (Test-Path $EnvFile) { docker @Compose down } else { Write-Host "Chua co site nao dang chay." }
  exit 0
}
if ($Action -eq "backup") {
  New-Item -ItemType Directory -Force backups | Out-Null
  $file = Join-Path "backups" "memohub-$(Get-Date -Format 'yyyyMMdd-HHmm').sql"
  # Dump inside the container and copy the file: piping through PowerShell would re-encode the text.
  docker @Compose exec -T db sh -c "pg_dump -U memohub memohub > /tmp/memohub-backup.sql"
  docker @Compose cp db:/tmp/memohub-backup.sql $file
  Write-Host "Da sao luu: $file"
  exit 0
}

# --- LAN IP of this computer (10.x / 192.168.x / 172.16-31.x), skipping virtual adapters ---
if (-not $Ip) {
  $cands = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
    $_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' -and
    $_.InterfaceAlias -notmatch 'vEthernet|WSL|Docker|Loopback|VirtualBox|VMware|Hyper-V' -and
    $_.AddressState -eq 'Preferred'
  } | Sort-Object { if ($_.IPAddress -like '10.*') { 0 } else { 1 } }
  if (-not $cands) { Write-Host "Khong tim thay IP mang noi bo. Chay lai: .\start-lan.ps1 start <IP-cua-may>"; exit 1 }
  $Ip = @($cands)[0].IPAddress
  if (@($cands).Count -gt 1) {
    Write-Host "May co nhieu IP: $((@($cands) | ForEach-Object { $_.IPAddress + ' (' + $_.InterfaceAlias + ')' }) -join ', ')"
    Write-Host "Dang dung $Ip. Neu sai: .\start-lan.ps1 start <IP-dung>"
  }
}
if ($Ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { Write-Host "IP khong hop le: $Ip"; exit 1 }

# --- .env.lan: created once (keys asked here, stored only on this computer) ---
if (-not (Test-Path $EnvFile)) {
  Write-Host "Lan dau chay: nhap API key (chi luu trong file .env.lan tren may nay, khong gui toi trinh duyet)."
  $openai = Read-Key "OpenAI API key (sk-...)"
  if (-not $openai.StartsWith("sk-")) { Write-Host "OpenAI key phai bat dau bang sk-"; exit 1 }
  $soniox = Read-Key "Soniox API key (Enter de bo qua)"
  $kid = "k" + (Get-Date -Format "yyyyMMdd")
  $secret = [Convert]::ToBase64String((New-Secret 32))
  $pg = -join ((New-Secret 18) | ForEach-Object { $_.ToString("x2") })
  Write-Utf8Lf $EnvFile @"
# Company-network site (start-lan.ps1). Contains secrets: never share or commit this file.
ENV_FILE=.env.lan
ENVIRONMENT=production
AUTH_MODE=shared
SESSION_COOKIE_SECURE=true
SESSION_TTL_MINUTES=10080
LAN_HOST=$Ip
LAN_HTTPS_PORT=443
LAN_HTTP_PORT=80
API_PORT=18000
TRUSTED_HOSTS=$Ip
PUBLIC_BASE_URL=https://$Ip
ENABLE_MOCK_PROVIDER=false
SEED_DEMO_DATA=false
EMBEDDED_WORKER=false
SECRET_ENCRYPTION_KEYS=${kid}:$secret
POSTGRES_PASSWORD=$pg
OPENAI_API_KEY=$openai
SERVER_AI_MODEL=gpt-4.1
SONIOX_API_KEY=$soniox
"@
  Write-Host "Da tao $EnvFile"
} else {
  # Keep the site address in sync with this computer's IP (e.g. after a DHCP change).
  $text = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot $EnvFile))
  $text = $text -replace '(?m)^LAN_HOST=.*$', "LAN_HOST=$Ip" -replace '(?m)^TRUSTED_HOSTS=.*$', "TRUSTED_HOSTS=$Ip" -replace '(?m)^PUBLIC_BASE_URL=.*$', "PUBLIC_BASE_URL=https://$Ip"
  # The API port is only for local diagnostics: keep it off 8000, which the dev stack uses.
  if ($text -notmatch '(?m)^API_PORT=') { $text = $text.TrimEnd() + "`nAPI_PORT=18000`n" }
  # The old default translation model translated Japanese <-> Vietnamese noticeably worse.
  if ($text -match '(?m)^SERVER_AI_MODEL=gpt-4\.1-mini[ \t]*$') {
    $text = $text -replace '(?m)^SERVER_AI_MODEL=gpt-4\.1-mini[ \t]*$', 'SERVER_AI_MODEL=gpt-4.1'
    Write-Host "Da doi model dich sang gpt-4.1 (chinh xac hon; muon tiet kiem: sua SERVER_AI_MODEL trong $EnvFile)."
  }
  Write-Utf8Lf $EnvFile $text
}

# --- Windows firewall: let colleagues reach ports 80/443 (needs Administrator once) ---
try {
  if (-not (Get-NetFirewallRule -DisplayName "MemoHub LAN" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "MemoHub LAN" -Direction Inbound -Protocol TCP -LocalPort 80, 443 -Action Allow -Profile Domain, Private | Out-Null
    Write-Host "Da mo firewall cho cong 80/443 (mang Domain/Private)."
  }
} catch {
  Write-Host "CANH BAO: chua mo duoc firewall (can quyen Administrator). Mo PowerShell 'Run as administrator' va chay:"
  Write-Host "  New-NetFirewallRule -DisplayName 'MemoHub LAN' -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow -Profile Domain,Private"
}
$profiles = Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object { $_.NetworkCategory -eq 'Public' }
if ($profiles) { Write-Host "CANH BAO: mang '$($profiles[0].Name)' dang de 'Public' - dong nghiep se khong truy cap duoc. Doi sang Private trong Settings > Network." }

# The dev stack (start.ps1, project "memohub") uses the same web port 3000: stop it (its data is kept).
$devRunning = docker ps --filter "label=com.docker.compose.project=memohub" --format "{{.Names}}"
if ($devRunning) {
  Write-Host "Dang tat site dev (start.ps1) de giai phong cong 3000 - du lieu dev van duoc giu."
  docker stop @($devRunning -split "`n" | Where-Object { $_ }) | Out-Null
}
$busy = Get-NetTCPConnection -State Listen -LocalPort 3000, 80, 443 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($busy) {
  $proc = (Get-Process -Id $busy.OwningProcess -ErrorAction SilentlyContinue).ProcessName
  if ($proc -and $proc -notmatch 'docker|com.docker|wslrelay|vpnkit') {
    Write-Host "CANH BAO: cong $($busy.LocalPort) dang bi chuong trinh '$proc' dung. Tat chuong trinh do, hoac doi LAN_HTTPS_PORT / LAN_HTTP_PORT trong $EnvFile."
  }
}

Write-Host "Dang build va khoi dong (lan dau co the mat 5-10 phut)..."
# Build one image at a time (api, migrate and worker share the backend image): parallel builds can
# time out in Docker Desktop ("DeadlineExceeded: no active session"). One retry per image.
foreach ($svc in @("api", "web")) {
  for ($try = 1; $try -le 2; $try++) {
    docker @Compose build $svc
    if ($LASTEXITCODE -eq 0) { break }
    if ($try -eq 1) { Write-Host "Build '$svc' loi, dang thu lai..."; Start-Sleep -Seconds 5 }
  }
  if ($LASTEXITCODE -ne 0) { Write-Host "Build '$svc' that bai. Kiem tra mang/Internet roi chay lai .\start-lan.cmd"; exit 1 }
}
docker @Compose up -d
if ($LASTEXITCODE -ne 0) { Write-Host "Loi khi khoi dong. Xem: docker $($Compose -join ' ') logs migrate api caddy --tail=50"; exit 1 }

Write-Host "Cho ung dung san sang..."
for ($i = 0; $i -lt 120; $i++) {
  try {
    Invoke-WebRequest -UseBasicParsing http://localhost:3000/login -TimeoutSec 3 | Out-Null
    # The root certificate of the site's local CA (Caddy creates it a moment after starting).
    for ($j = 0; $j -lt 15 -and -not (Test-Path memohub-ca.crt); $j++) {
      docker @Compose cp caddy:/data/caddy/pki/authorities/local/root.crt memohub-ca.crt 2>$null | Out-Null
      if (-not (Test-Path memohub-ca.crt)) { Start-Sleep -Seconds 2 }
    }
    if (Test-Path memohub-ca.crt) { Write-Host "Chung chi goc cua site: memohub-ca.crt (cung tai duoc o http://$Ip/ca.crt)" }
    Write-Host ""
    Write-Host "SAN SANG. Gui cho dong nghiep:  https://$Ip"
    Write-Host "  - Lan dau trinh duyet bao 'khong an toan': bam Nang cao > Tiep tuc (hoac cai chung chi o duoi)."
    Write-Host "  - Bo canh bao vinh vien: tai http://$Ip/ca.crt, mo file > Install Certificate >"
    Write-Host "    Current User > 'Trusted Root Certification Authorities'. Roi mo lai trinh duyet."
    Write-Host "Tren may nay co the dung: http://localhost:3000"
    Write-Host "Dung site: .\start-lan.ps1 stop    Sao luu du lieu: .\start-lan.ps1 backup"
    exit 0
  } catch { Start-Sleep -Seconds 3 }
}
Write-Host "Het thoi gian cho. Xem log: docker $($Compose -join ' ') logs --tail=50"; exit 1
