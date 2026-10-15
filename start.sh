#!/usr/bin/env bash
# One-command local start (macOS / Linux). Usage: ./start.sh   — stop: ./start.sh stop
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "stop" ]; then docker compose down; exit 0; fi

command -v docker >/dev/null 2>&1 || { echo "❌ Chưa cài Docker. Cài Docker Desktop: https://www.docker.com/products/docker-desktop/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "❌ Docker chưa chạy. Hãy mở Docker Desktop rồi chạy lại."; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  KEY=$(head -c 32 /dev/urandom | base64 | tr -d '\n')
  sed -i.bak "s|^SECRET_ENCRYPTION_KEYS=.*|SECRET_ENCRYPTION_KEYS=kdev:${KEY}|" .env && rm -f .env.bak
  echo "✅ Đã tạo file .env (kèm khóa mã hóa)"
fi

echo "⏳ Đang build và khởi động (lần đầu có thể mất 3–10 phút)…"
docker compose up --build -d

echo "⏳ Chờ ứng dụng sẵn sàng…"
for _ in $(seq 1 120); do
  if curl -fsS -o /dev/null http://localhost:3000/login 2>/dev/null; then
    echo "✅ Sẵn sàng: http://localhost:3000  (đăng nhập: Trần Minh (PM) – pm@example.com)"
    (command -v open >/dev/null && open http://localhost:3000) || (command -v xdg-open >/dev/null && xdg-open http://localhost:3000) || true
    exit 0
  fi
  sleep 3
done
echo "❌ Hết thời gian chờ. Xem log: docker compose logs --tail=50"
exit 1
