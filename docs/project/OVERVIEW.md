# OVERVIEW — назначение, возможности и статус

## 1. Назначение

Проект `rustdesk-ab-backend` — self-hosted backend для **штатного, немодифицированного**
клиента RustDesk. Он решает три задачи:

1. **Адресная книга.** Реализует совместимый с RustDesk Server Pro HTTP API
   `/api/*`: вход, личная и общие книги, устройства, теги, права.
2. **Панель управления.** React SPA на `/app/` и legacy server-rendered
   панель на `/panel/` для работы с книгами, устройствами, тегами,
   пользователями и обнаруженными устройствами.
3. **KX-shim.** Завершает server-first `KeyExchange` на TCP `21116`, без
   которого залогиненный клиент RustDesk 1.4.x не проходит secure rendezvous
   против OSS `hbbs`, и проксирует расшифрованный трафик в настоящий `hbbs`.

Проект **не является** заменой `hbbs`/`hbbr`, не реализует relay-протокол,
не предоставляет удалённый рабочий стол и не требует правок клиента.

## 2. Технологический стек

| Слой | Технологии | Источник |
|---|---|---|
| HTTP API | Python 3.13, FastAPI, Starlette, Uvicorn | `requirements.txt`, `Dockerfile` |
| ORM/БД | SQLAlchemy 2.x, Alembic, SQLite (по умолчанию), psycopg для PostgreSQL | `requirements.txt`, `app/db/`, `alembic/` |
| Валидация/настройки | Pydantic 2, pydantic-settings | `app/schemas/`, `app/core/config.py` |
| Пароли/токены | bcrypt, `secrets.token_urlsafe` | `app/core/security.py` |
| Шифрование паролей устройств | Fernet (cryptography) | `app/core/crypto.py` |
| Rendezvous/KX | protobuf, PyNaCl (`crypto_box`, `crypto_secretbox`) | `app/shim/` |
| Legacy-панель | Jinja2, cookie-сессия Starlette | `app/api/panel.py`, `app/web/templates/` |
| SPA | React 19, TypeScript, Vite 8, Tailwind CSS 4, React Router 7 | `frontend/package.json` |
| Сборка/деплой | Docker multi-stage, Docker Compose, Node 22 для frontend | `Dockerfile`, `docker-compose.yml` |

Версии в `requirements.txt` заданы диапазонами, а не lock-файлом Python.
`frontend/package-lock.json` фиксирует npm-зависимости.

## 3. Компоненты и ответственность

| Компонент | Точка входа | Ответственность |
|---|---|---|
| Запуск приложения | `app/__main__.py` | проверка настроек, каталоги/права, `alembic upgrade head`, запуск Uvicorn |
| FastAPI-приложение | `app/main.py` | lifespan, middleware, роутеры, health, монтирование SPA |
| RustDesk API | `app/api/rustdesk.py` | контракт клиента `/api/*`, сессии, книги, peers, tags, heartbeat, sysinfo |
| Внутренний API | `app/api/webapi.py` | `/api/v1/*`: расширенные модели для SPA, bulk-операции, discovery, users |
| Legacy-панель | `app/api/panel.py` | HTML-страницы `/panel/*` на cookie-сессии |
| Доменные сервисы | `app/services/` | права книг, auth-сессии, presence, sysinfo, discovery |
| Модели | `app/models/models.py` | 9 таблиц SQLAlchemy |
| Shim | `app/shim/shim.py` | TCP KX/plain proxy, UDP relay, discovery-события, лимиты |
| Супервизор шима | `app/shim_supervisor.py` | фоновый поток, bounded backoff, статус для `/health/ready` |
| SPA | `frontend/src/` | экраны Devices/Books/Tags/Users/Login, API-клиент |
| Миграции | `alembic/versions/` | схема 0001–0004 |
| CLI | `app/cli.py` | `create-admin`, `gen-key`, `dump-book`, `backup` |

## 4. Ключевые пользовательские сценарии

### 4.1. Первый запуск

`python -m app` → проверка `DEVICE_SECRET`/`WEB_SECRET` → создание `data/`,
`logs/`, выставление прав → миграции → Uvicorn → (опционально) шим.
Первый администратор создаётся отдельно: `python -m app.cli create-admin`.

### 4.2. Вход клиента RustDesk и адресная книга

Клиент вызывает `/api/login`, получает opaque Bearer token и работает с
`/api/ab/personal`, `/api/ab/shared/profiles`, `/api/ab/peers`,
`/api/ab/peer/*`, `/api/ab/tag/*`. Для каждого запроса перепроверяются
владелец книги и `rule` (1/2/3). Ошибки имеют вид `{"error": ...}`.

### 4.3. Панель

SPA (`/app/`) использует тот же Bearer token, но внутренние эндпоинты
`/api/v1/*`. Пользователь видит книги, устройства, теги, presence,
discovered-устройства, карточку устройства с sysinfo и умеет выполнять
bulk-удаление/массовое изменение тегов. Legacy-панель (`/panel/`) остаётся
для базового CRUD на cookie-сессии.

### 4.4. Подключение к устройству через шим

Залогиненный клиент идёт на `SHIM_LISTEN` (обычно `0.0.0.0:21116`). Шим
первым отправляет `KeyExchange` с подписью ключом `hbbs`, принимает
клиентский `KeyExchange`, переключается на secretbox и проксирует
расшифрованные protobuf-сообщения в `SHIM_UPSTREAM` — настоящий rendezvous
`hbbs`. Разлогиненный/plain-клиент проксируется без шифрования. UDP
rendezvous на том же порту проксируется отдельно, без криптографии (так
устроен протокол).

### 4.5. Presence и инвентаризация

- `/api/heartbeat` (без auth) штампует `address_book_entries.last_seen` для
  совпадающих ID; `online` = heartbeat не старше 45 секунд, иначе `offline`;
  никогда не видели — `unknown`.
- `/api/sysinfo` (без auth) принимает от клиента hostname, username, OS, CPU,
  RAM, версию. Хранятся только поля из белого списка; `uuid` и option-поля
  (в которых могут быть пароли книг) отбрасываются.
- Shim discovery пишет в `discovered_devices` факт появления ID в
  `register_peer`/`register_pk`; это **не** identity и **не** sysinfo.

## 5. Что реализовано

Подтверждено кодом и историей:

- вход/выход, opaque-сессии с истечением и отзывом;
- личная книга, shared-книги, права `read`/`readWrite`/`fullControl`;
- CRUD устройств, теги (цвет, переименование), many-to-many `entry_tags`;
- поиск, фильтры по тегам AND/OR, `untagged`, presence, сортировка,
  пагинация;
- bulk-удаление и bulk-теги с частичным успехом;
- администрирование пользователей (создание, переименование, disable,
  смена пароля, удаление);
- presence по heartbeat, честные `online/offline/unknown`;
- sysinfo с парсингом CPU/RAM/OS и запросом повторной отправки;
- discovery через shim, сохранение истории, stale-sweep;
- KX-shim TCP (secure + plain) и UDP relay, лимиты, супервизор;
- SPA и legacy-панель;
- Docker-образ с non-root, автосекретами и healthcheck (**Docker-файлы
  сейчас не в git** — см. `docs/development/WORKFLOW.md` §1);
- CLI backup/restore-совместимый (`backup` создаёт копию с `integrity_check`).

## 6. Что ограничено или не реализовано

Это не «планы», а фактическое состояние:

- **Relay `21117`, WebSocket, WebRTC, удалённые сессии** — вне проекта;
  клиент ходит в `hbbr` напрямую.
- **Аутентификация на rendezvous-порту** отсутствует в протоколе; шим
  полагается на лимиты и сетевую изоляцию.
- **Sysinfo** работает только у клиентов, у которых настроен custom
  `api-server` или API доступен на вычисляемом порту `21114`; при API на
  `8000` и пустом поле API данных не будет.
- **Discovery** видит только TCP/UDP через шим; relay/P2P и `LoginRequest`/
  `PeerInfo` ему недоступны. Очередь discovery — in-memory, при рестарте
  необработанные события теряются.
- **2FA/TFA/verificationCode** поля принимаются в `/api/login`, но не
  реализованы.
- **Группы устройств** — заглушки `{total:0,data:[]}`; полноценных групп нет.
- **PostgreSQL** заявлен в `DATABASE_URL` и зависимостях, но фактическая
  проверка/поддержка миграций выполнялась на SQLite; считать PostgreSQL
  непроверенным.
- **Автоматических тестов нет** (см. `docs/development/TESTING.md`).
- **Часть security-замечаний остаётся открытой** (см. `docs/SECURITY.md`).

## 7. Границы проекта

| В проекте | Не в проекте |
|---|---|
| Address Book API | Замена `hbbs`/`hbbr` |
| Web Panel | Мобильное приложение |
| KX-shim для secure rendezvous | Патч клиента RustDesk |
| Presence по heartbeat | Реальное online-состояние из `hbbs` |
| Discovery по shim | Инвентаризация всех устройств сети |
| SQLite + Alembic | Автоматический HA/кластер |

## 8. Куда читать дальше

- Устройство и потоки: `docs/project/ARCHITECTURE.md`
- Файлы и точки изменения: `docs/project/REPOSITORY_MAP.md`
- Схема БД: `docs/project/DATA_MODEL.md`
- API: `docs/project/API_REFERENCE.md`
- Запуск: `docs/development/WORKFLOW.md`
- Проверки: `docs/development/TESTING.md`
- Безопасность: `docs/SECURITY.md`
- История ошибок: `docs/knowledge/ERRORS.md`
