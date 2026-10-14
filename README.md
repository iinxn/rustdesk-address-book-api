# RustDesk Manager

Единое приложение: **FastAPI** (Address Book API, совместимый с обычным
RustDesk Client без его изменений) + **Web Panel** (React SPA + legacy `/panel`)

+ **KX Shim** (прокси secure-rendezvous 21116 → OSS hbbs). База — SQLite
  `data/base.db`, миграции Alembic.

## Быстрый старт (Debian)

```bash
python3 -m venv --without-pip .venv
.venv/bin/python /tmp/get-pip.py        # Debian python без ensurepip
.venv/bin/pip install -r requirements.txt
cp .env.example .env                    # заполнить секреты (ниже)
.venv/bin/python -m app.cli gen-key     # -> DEVICE_SECRET в .env
./scripts/start.sh                      # одна команда: миграции + API + shim
```

`.env` минимум:

```bash
DEVICE_SECRET='<gen-key>'
WEB_SECRET='<openssl rand -hex 32>'
# SHIM_ENABLED=1 + SHIM_ID_KEY=/abs/path/id_ed25519  — для шима
```

Проверка: `http://localhost:8000/health/ready`, панель `http://localhost:8000/app/`,
API `http://localhost:8000/docs`. Первый админ: `.venv/bin/python -m app.cli create-admin`.

## RustDesk Client

API Server: `http://<ip>:8000` (или https через reverse proxy — см.
`docs/deployment-debian.md`). ID/Relay Server + Key — как раньше.

## Документы

- `docs/architecture.md` — схема, порты, потоки.
- `docs/threat-model.md` — модель угроз и принятые риски.
- `docs/security-audit.md` — аудит: находки, исправления, проверки.
- `docs/deployment-debian.md` — установка, systemd, HTTPS, обновление.
- `docs/backup-restore.md` — бэкап/восстановление.
- `docs/connection-diagnostic.md`, `docs/kx-shim-spec.md` — диагностика
  `Failed to secure tcp` и протокол шима.
- `docs/rustdesk-api-analysis.md`, `docs/web-panel.md` — контракт API и панель.

## Тесты

```bash
.venv/bin/pytest -q        # вся сюита, включая security-тесты
```

## Скрипты

- `scripts/start.sh` / `scripts/stop.sh` — запуск/остановка.
- `.venv/bin/python -m app.cli backup [--dest ...]` — консистентный бэкап.
- `.venv/bin/python -m app.cli dump-book <guid>` — redacted-дамп книги.
