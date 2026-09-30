# RustDesk Address Book Backend (MVP)

Собственный backend для Address Book RustDesk Server Pro. Обычный RustDesk Client
работает без изменений. Детали протокола: `docs/rustdesk-api-analysis.md`.

## Быстрый старт (Debian)

```bash
cd /home/user/Documents/rustdesk-ab-backend
python3 -m venv --without-pip .venv   # если .venv уже есть — пропустить
.venv/bin/python /tmp/opencode/get-pip.py  # один раз (pip отсутствует в Debian python)
.venv/bin/pip install -r requirements.txt

# Вариант A: PostgreSQL через docker (когда доступен docker)
docker compose up -d postgres
export DATABASE_URL='postgresql+psycopg://rustdesk:rustdesk@localhost:5432/rustdesk_ab'

# Вариант B: SQLite для разработки без docker/sudo (по умолчанию)
export DATABASE_URL='sqlite:///./dev.db'

.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli gen-key   # -> положить в .env как DEVICE_SECRET
cp .env.example .env                  # и заполнить
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Проверка: `http://localhost:8000/health`, docs: `http://localhost:8000/docs`,
новая панель: `http://localhost:8000/app/` (после `cd frontend && npm run build`),
старая панель: `http://localhost:8000/panel/devices`. Детали: `docs/web-panel.md`.

## Первый администратор

```bash
.venv/bin/python -m app.cli create-admin
# спросит username + password
```

## Тесты

```bash
.venv/bin/pytest -q
```

## Настройка RustDesk Client

`Settings -> Network -> API server / Sync address book`: `http://<ip-debian>:8000`.
Логин в клиенте — username/password из `create-admin`.

## Переменные (.env)

| Var                 | Default                | Назначение                                                           |
| ------------------- | ---------------------- | ------------------------------------------------------------------------------ |
| `DATABASE_URL`    | `sqlite:///./dev.db` | postgres:`postgresql+psycopg://rustdesk:rustdesk@localhost:5432/rustdesk_ab` |
| `DEVICE_SECRET`   | (пусто=ephemeral) | Fernet-ключ (`cli gen-key`) для `password_encrypted`                |
| `WEB_SECRET`      | dev-default            | cookie-секрет панели                                               |
| `SESSION_DAYS`    | 30                     | срок токена                                                          |
| `MAX_PEER_ONE_AB` | 0                      | лимит устройств (0=без лимита)                          |
