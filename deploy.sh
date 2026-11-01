#!/bin/bash
set -e

# Конфиг
REPO="https://github.com/YOUR_ORG/blrdai.git"
BRANCH="${1:-main}"
USER="blrd"
HOME="/home/blrd"
APP="$HOME/app"
DOMAIN="${DOMAIN:-ai.example.com}"
EMAIL="${EMAIL:-admin@example.com}"

echo "=== blrd ai: развёртывание ==="
echo "Домен: $DOMAIN, ветка: $BRANCH"

# 1. Пользователь и папки
if ! id "$USER" &>/dev/null; then
  echo "→ Создаю пользователя $USER"
  useradd -m -s /bin/bash "$USER"
fi

sudo -u "$USER" mkdir -p "$APP" "$HOME/.env.d"
cd "$APP"

# 2. Клон репо
if [ ! -d .git ]; then
  echo "→ Клонирую $REPO"
  sudo -u "$USER" git clone --depth 1 -b "$BRANCH" "$REPO" .
else
  echo "→ Обновляю репо"
  sudo -u "$USER" git fetch origin "$BRANCH"
  sudo -u "$USER" git reset --hard "origin/$BRANCH"
fi

# 3. .env
ENV_FILE="$APP/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "→ Создаю .env (заполните вручную перед запуском)"
  cat > "$ENV_FILE" << 'EOF'
DATABASE_URL=postgresql+asyncpg://blrd:change-me@localhost:5432/blrd
BOT_TOKEN=123456:ABCDEF...
BOT_USERNAME=blrd_ai_bot
WEBAPP_URL=https://DOMAIN.com
ANYMODEL_API_KEY=sk-...
PLATEGA_MERCHANT_ID=...
PLATEGA_SECRET=...
SECRET_KEY=change-me-to-64-random-chars
ADMIN_PASSWORD=change-me
ADMIN_IDS=123456789
LOG_LEVEL=INFO
EOF
  chown "$USER:$USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "   ⚠️  Отредактируйте: nano $ENV_FILE"
  echo "   Затем перезапустите: $0"
  exit 0
fi

# 4. PostgreSQL (если нет)
if ! command -v psql &> /dev/null; then
  echo "→ Устанавливаю PostgreSQL"
  apt-get update && apt-get install -y postgresql postgresql-contrib
  systemctl start postgresql
  systemctl enable postgresql
fi

if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw blrd; then
  echo "→ Создаю БД и пользователя"
  DB_PASS=$(grep DB_PASSWORD "$ENV_FILE" | cut -d= -f2)
  sudo -u postgres createuser blrd || true
  sudo -u postgres psql -c "ALTER USER blrd WITH PASSWORD '$DB_PASS';"
  sudo -u postgres createdb -O blrd blrd
fi

# 5. Python окружение
echo "→ Настраиваю Python"
sudo -u "$USER" python3 -m venv "$APP/venv" || true
sudo -u "$USER" "$APP/venv/bin/pip" install -q --upgrade pip
sudo -u "$USER" "$APP/venv/bin/pip" install -q -r "$APP/requirements.txt"

# 6. systemd для приложения
echo "→ Создаю systemd-сервис blrd-app"
cat > /etc/systemd/system/blrd-app.service << EOF
[Unit]
Description=blrd ai Application
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=notify
User=$USER
WorkingDirectory=$APP
Environment="PATH=$APP/venv/bin"
EnvironmentFile=$ENV_FILE
ExecStart=$APP/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 7. systemd для бота
echo "→ Создаю systemd-сервис blrd-bot"
cat > /etc/systemd/system/blrd-bot.service << EOF
[Unit]
Description=blrd ai Bot
After=network.target
Wants=blrd-app.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP
Environment="PATH=$APP/venv/bin"
EnvironmentFile=$ENV_FILE
ExecStart=$APP/venv/bin/python run_bot.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable blrd-app blrd-bot

# 8. nginx
echo "→ Настраиваю nginx"
apt-get install -y nginx certbot python3-certbot-nginx

cat > /etc/nginx/sites-available/blrd << EOF
server {
    server_name $DOMAIN;
    listen 80;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
    }

    # SSE (стрим генерации): не буферим
    location /api/chats/*/send {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header X-Accel-Buffering no;
    }
}
EOF

ln -sf /etc/nginx/sites-available/blrd /etc/nginx/sites-enabled/ || true
rm -f /etc/nginx/sites-enabled/default

if ! nginx -t &>/dev/null; then
  echo "   ⚠️  nginx конфиг ошибка, проверьте"
  nginx -t
  exit 1
fi

# 9. SSL (Certbot)
echo "→ Настраиваю SSL (Certbot)"
certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email --non-interactive || true

systemctl restart nginx

# 10. Старт сервисов
echo "→ Запускаю сервисы"
systemctl start blrd-app blrd-bot

echo ""
echo "=== ✅ Развёртывание готово ==="
echo "   Домен: https://$DOMAIN"
echo "   Бот: @$BOT_USERNAME"
echo "   Логи: journalctl -u blrd-app -f"
echo ""
echo "Чтобы остановить: systemctl stop blrd-app blrd-bot"
echo "Перезапуск конфига: systemctl restart blrd-app"
