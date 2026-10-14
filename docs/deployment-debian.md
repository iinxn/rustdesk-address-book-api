# Deployment (Debian)

Целевая платформа: Debian + KDE Plasma, отдельный непривилегированный
пользователь, systemd. Root не требуется (все порты >1024).

## Установка

```bash
sudo useradd -r -m -d /opt/rustdesk-manager rustdesk   # один раз, нужен sudo
sudo cp -r /home/user/Documents/rustdesk-manager /opt/rustdesk-manager
sudo chown -R rustdesk:rustdesk /opt/rustdesk-manager
sudo -u rustdesk python3 -m venv --without-pip /opt/rustdesk-manager/.venv
# pip + зависимости (см. README), затем:
sudo cp config/rustdesk-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## Конфигурация (`/opt/rustdesk-manager/.env`, владелец rustdesk, 0600)

```bash
DEV_MODE=0
HOST=127.0.0.1          # 0.0.0.0 чтобы слушать LAN (API :8000)
PORT=8000
DEVICE_SECRET='<из: .venv/bin/python -m app.cli gen-key>'
WEB_SECRET='<из: openssl rand -hex 32>'
SHIM_ENABLED=1
SHIM_LISTEN=0.0.0.0:21116     # открыт наружу сознательно, caps включены
SHIM_UPSTREAM=127.0.0.1:21166 # hbbs, запущенный с -p 21166 (НЕ relay-порт 21117!)
SHIM_ID_KEY=/opt/rustdesk-manager/keys/id_ed25519  # 0600, НЕ в репозитории
```

```bash
sudo systemctl enable --now rustdesk-manager
curl http://127.0.0.1:8000/health/ready
```

## HTTPS (обязательно для недоверенных сетей)

Приложение само TLS не терминирует. Схема: Caddy/Nginx → `127.0.0.1:8000`.
Пример Caddyfile — `config/Caddyfile.example`. Проверки:

```bash
curl --cacert <ca.crt> https://<host>/health/ready
```

Диагностический стенд с локальным CA и сравнением HTTP/HTTPS:
`~/Documents/rustdesk-diagnostic/` (`docs/connection-diagnostic.md`).

## Windows-тестирование (инструкция)

1. API Server в клиенте: `http(s)://<ip-debian>:8000`, login пользователем.
2. ID/Relay Server + Key — как раньше (наш API их не меняет).
3. Login → Address Book → connect; сверить статусы в Web Panel.
4. Shim на Debian НЕ работает под Windows (asyncio/Python — технически
   переносим, но целевой кейс — Debian; Windows тестируется только как
   RustDesk Client, установки не требует).

## Обновление

```bash
.venv/bin/python -m app.cli backup      # сначала бэкап
git pull / копия новых файлов
.venv/bin/python -m app                 # миграции применятся сами
sudo systemctl restart rustdesk-manager
```

## Мониторинг

- `/health/live` — процесс жив; `/health/ready` — БД + шим готовы
  (503 + причина, если нет).
- Логи: `logs/app.log` (uvicorn stdout при ручном старте) / journald при
  systemd. Секретов в логах нет (аудит).
