#!/usr/bin/env bash
# One-command local start (macOS / Linux).
#   ./start.sh            normal start
#   ./start.sh sandbox    + FAKE Teams/Zoom/Google Meet server to try the integrations (dev/test only)
#   ./start.sh stop
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE=(docker compose -f docker-compose.yml)
if [ "${1:-}" = "sandbox" ] || [ "${1:-}" = "stop" ]; then COMPOSE+=(-f docker-compose.sandbox.yml); fi

if [ "${1:-}" = "stop" ]; then "${COMPOSE[@]}" down --remove-orphans; exit 0; fi

command -v docker >/dev/null 2>&1 || { echo "❌ Chưa cài Docker. Cài Docker Desktop: https://www.docker.com/products/docker-desktop/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "❌ Docker chưa chạy. Hãy mở Docker Desktop rồi chạy lại."; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  KEY=$(head -c 32 /dev/urandom | base64 | tr -d '\n')
  sed -i.bak "s|^SECRET_ENCRYPTION_KEYS=.*|SECRET_ENCRYPTION_KEYS=kdev:${KEY}|" .env && rm -f .env.bak
  echo "✅ Đã tạo file .env (kèm khóa mã hóa)"
fi

# .env must use LF line endings: a Windows CRLF ("\r") would corrupt every value (e.g. "false\r").
if grep -q $'\r' .env 2>/dev/null; then
  sed -i.bak 's/\r$//' .env && rm -f .env.bak
  echo "✅ Đã chuẩn hóa xuống dòng trong .env (CRLF → LF)"
fi

# Docker Compose reads "KEY=   # comment" as the value "# comment": drop comments after empty values
# (older .env files copied from .env.example contained such lines).
if grep -qE '^[A-Za-z0-9_]+=[[:space:]]+#' .env 2>/dev/null; then
  sed -i.bak -E 's/^([A-Za-z0-9_]+=)[[:space:]]+#.*$/\1/' .env && rm -f .env.bak
  echo "✅ Đã sửa các dòng chú thích sau biến trống trong .env"
fi

echo "⏳ Đang build và khởi động (lần đầu có thể mất 3–10 phút)…"
"${COMPOSE[@]}" up --build -d

echo "⏳ Chờ ứng dụng sẵn sàng…"
for _ in $(seq 1 120); do
  if curl -fsS -o /dev/null http://localhost:3000/login 2>/dev/null; then
    echo "✅ Sẵn sàng: http://localhost:3000  (đăng nhập: Trần Minh (PM) – pm@example.com)"
    if [ "${1:-}" = "sandbox" ]; then
      echo "🧪 SANDBOX: Teams/Zoom/Google Meet là máy chủ GIẢ LẬP (localhost:9100). Vào 'Tích hợp nền tảng' để thử."
      echo "   Hướng dẫn: docs/integrations/sandbox-vi.md"
    fi
    (command -v open >/dev/null && open http://localhost:3000) || (command -v xdg-open >/dev/null && xdg-open http://localhost:3000) || true
    exit 0
  fi
  sleep 3
done
echo "❌ Hết thời gian chờ. Xem log: docker compose logs --tail=50"
exit 1
