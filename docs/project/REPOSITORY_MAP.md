# REPOSITORY_MAP — навигация по коду

Цель — быстро найти место изменения и связанные файлы. Это не список всех
файлов, а карта ответственности.

## 1. Верхний уровень

| Путь | Назначение |
|---|---|
| `app/` | Python-бэкенд: FastAPI, сервисы, модели, shim, legacy-шаблоны |
| `frontend/` | React SPA (исходники, собранный `dist/`) |
| `alembic/` | конфигурация и версии миграций |
| `alembic.ini` | Alembic config; `script_location` задаётся в `__main__.py` |
| `scripts/` | запуск/остановка, Docker entrypoint, диагностика, экспорт книг |
| `config/` | примеры Caddy и systemd (не production-hardened) |
| `data/` | runtime: SQLite, `.secrets.env`, pid-файл (не коммитится) |
| `logs/` | создаётся при старте; приложение само файл лога не пишет |
| `Dockerfile`, `docker-compose.yml` | сборка/запуск контейнера (**сейчас в `.gitignore`, не в git**) |
| `requirements.txt` | Python-зависимости (без lock-файла) |
| `requirements-dev.txt` | тестовые зависимости (`pytest`, `httpx`), не в runtime |
| `tests/` | автотесты; временная SQLite, не `data/` |
| `pytest.ini` | конфигурация pytest и маркер `slow` |
| `README.md`, `docs/ru.md`, `docs/en.md` | публичная документация и быстрый старт |
| `TODO.md` | состояние разработки, следующие задачи, долг, блокеры |
| `docs/project/`, `docs/development/`, `docs/knowledge/` | внутренняя документация для разработки/агентов |
| `.opencode/skills/` | Skills: `project-debugging`, `sqlite-changes` |
| `SECURITY_AUDIT.md` | исторический аудит SEC-001…SEC-020 (не в git) |

## 2. Точки входа

| Файл | Что делает | Когда трогать |
|---|---|---|
| `app/__main__.py` | fail-fast настройки, каталоги/права, миграции, Uvicorn | изменение порядка старта, миграций, прав |
| `app/main.py` | FastAPI app, middleware, lifespan, health, SPA mount | новый router/middleware, health, монтирование |
| `app/cli.py` | `create-admin`, `gen-key`, `dump-book`, `backup` | операции обслуживания |
| `app/shim/shim.py` | standalone/embedded shim: TCP KX, UDP relay | протокол, лимиты, discovery |
| `app/shim_supervisor.py` | поток, backoff, статус шима | рестарты, health |
| `scripts/start.sh` / `stop.sh` | foreground-запуск и остановка | эксплуатация на хосте |
| `scripts/docker-entrypoint.sh` | генерация/переиспользование секретов | Docker secrets |

## 3. Backend по каталогам

### `app/api/`

| Файл | Содержимое | Замечания |
|---|---|---|
| `rustdesk.py` | `/api/login`, `/api/currentUser`, `/api/logout`, `/api/login-options`, `/api/ab/*`, `/api/heartbeat`, `/api/sysinfo*`, legacy-заглушки | Контракт клиента. Ошибки `{"error": ...}`. Не добавляй сюда поля панели |
| `webapi.py` | `/api/v1/*`: stats, books, entries, bulk, tags, discovered, device-info, users | Внутренний API SPA. Ошибки `{"detail": ...}`. Много ручной авторизации |
| `panel.py` | `/panel/*`: login/logout, devices, tags, users | Legacy HTML, cookie-сессия; при изменении проверяй CSRF/disable |
| `deps.py` | `bearer_token`, `current_user`, `optional_user` | Единая проверка Bearer |

Ключевые функции `webapi.py`:

- `books_visible()` — admin видит все книги, остальные — свои + shared по
  permission;
- `entry_out()` — расширенное представление устройства (presence, tags,
  tag_objs, sysinfo-fallback, timestamps);
- `_dedupe_ids()` / `_clean_tag_names()` — лимиты bulk;
- `_books_for_rids()` — какие видимые книги содержат ID (один запрос);
- `_discovered_out()` — форма discovered + `in_books` + `info`;
- `_book_counts()` — счётчики presence для книги.

### `app/services/`

| Файл | Ответственность | Основные функции |
|---|---|---|
| `ab.py` | книги, права, peers, теги | `personal_book`, `get_book_for_user`, `rule_for`, `can_write`, `shared_profiles`, `peer_out`, `sync_entry_tags`, `add_entry_tags`, `remove_entry_tags`, `apply_peer_update`, `tag_usage` |
| `auth.py` | пользователи и opaque-сессии | `create_user` (создаёт личную книгу, принимает `display_name`), `clean_display_name`, `authenticate`, `create_session`, `destroy_user_sessions`, `purge_expired_sessions`, `user_by_token`, `destroy_session` |
| `presence.py` | presence по heartbeat | `record_heartbeat`, `status_of`; `HEARTBEAT_SEC=15`, `ONLINE_AFTER_SEC=45` |
| `device_info.py` | sysinfo (write-once), refresh/approval | `save_sysinfo`, `device_known`, `missing_fields`, `parse_cpu`, `parse_memory`, `parse_os`, `record_heartbeat`, `request_refresh`, `take_refresh`, `take_approval`, `info_out` |
| `discovery.py` | drain очереди → БД | `reset_online`, `drain_once` (upsert, merge source, stale sweep) |
| `discovery_events.py` | потокобезопасная очередь | `publish`, `drain`, `qsize`, `dropped_count`; `MAX_EVENTS=20000` |

### `app/core/`

| Файл | Ответственность |
|---|---|
| `config.py` | все env-настройки, `resolved_database_url`, fail-fast секретов, `docs_enabled` |
| `security.py` | bcrypt, `new_token` |
| `crypto.py` | Fernet для паролей устройств; ephemeral key при пустом `DEVICE_SECRET` (dev) |
| `validators.py` | `validate_rustdesk_id`: запрет `@ / \ ? & =`, пробелов; regex `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` |
| `middleware.py` | `client_ip`, `BodyCapMiddleware`, `RateLimitMiddleware`, `heartbeat_allow`, `reset_rate_limits` |
| `logging.py` | `basicConfig`; файлового handler нет |

### `app/models/`, `app/schemas/`, `app/db/`

| Путь | Содержимое |
|---|---|
| `app/models/models.py` | `User`, `Session`, `AddressBook`, `AddressBookEntry`, `Tag`, `EntryTag`, `AddressBookPermission`, `DiscoveredDevice`, `DeviceInfo` |
| `app/schemas/rustdesk.py` | `LoginIn`, `UserOut`, `LoginOut`, `PeerOut`, `PeersPage`, `TagOut`, `SharedProfileOut`, `SharedProfilesPage`, `ErrorOut` |
| `app/schemas/panel.py` | `EntryIn`, `TagIn`, `UserIn`, `BulkIdsIn`, `BulkTagsIn`, `DiscoveredAddIn`, `AddressBookOut`, `EntryOut`, `TagOut`, `UserOut` |
| `app/db/base.py` | `Base` |
| `app/db/session.py` | engine, SQLite `PRAGMA foreign_keys=ON` + `busy_timeout=5000`, `SessionLocal`, `get_db`, `check_ready` |
| `app/web/templates/` | Jinja-шаблоны legacy-панели (`base`, `login`, `devices`, `tags`, `users`) |

### `app/shim/`

| Файл | Содержимое |
|---|---|
| `shim.py` | `SessionCrypt` (secretbox v0), `load_sign_sk`, `Gate`, `_DiscoveryGuard`, `_ConnTracker`, `handle/_handle`, `UdpRelay`, `amain`, CLI |
| `rendezvous_pb2.py` | сгенерированный protobuf; менять только вместе с `.proto` и `grpcio-tools` |

Ключевые константы: `FIRST_TIMEOUT=40`, `READ_TIMEOUT=60`, `MAX_FRAME=2 MiB`,
`MAX_CONNS=200`, `MAX_CONNS_PER_MIN_PER_IP=30`, `UDP_IDLE_TIMEOUT=120`,
`UDP_SWEEP_INTERVAL=30`, `DISCOVERY_MAX_PARSE=4096`,
`DISCOVERY_NEW_IDS_PER_IP_PER_MIN=30`, `DISCOVERY_REMEMBER_SEC=1800`.

## 4. Frontend

| Файл | Назначение |
|---|---|
| `frontend/src/api.ts` | `req()`, `ApiError`, хранение токена в `localStorage`, все вызовы `/api/v1` и `/api/login` |
| `frontend/src/types.ts` | контрактные типы, `parseUtc`, `relTime(iso, lang)`, `colorCss`, `textOnColor` |
| `frontend/src/App.tsx` | провайдеры i18n и уведомлений, HashRouter, Guard по наличию токена, маршруты |
| `frontend/src/i18n.tsx` | словари RU/EN, `I18nProvider`, `useI18n()`, `translate()`; выбор языка в `localStorage` |
| `frontend/src/notifications.tsx` | `NotificationProvider`, `useNotify()`, глобальный хост тостов сверху |
| `frontend/src/components.tsx` | Layout, навигация, Brand, LangSwitch, ProfileDialog (свой display name), Badge, TagBadge, Modal, Confirm, Pagination |
| `frontend/src/hooks.ts` | `useDebounce`, `useTheme` (светлая тема по умолчанию) |
| `frontend/src/pages/Devices.tsx` | основной экран: книги, поиск/фильтры, presence, discovered, bulk, карточка устройства, sysinfo |
| `frontend/src/pages/Books.tsx` | список/создание/переименование/удаление книг |
| `frontend/src/pages/Tags.tsx` | теги, цвета, переименование, удаление |
| `frontend/src/pages/Users.tsx` | администрирование пользователей, display name |
| `frontend/src/pages/Login.tsx` | вход, сохранение сессии, брендинг |
| `frontend/vite.config.ts` | `base: '/app/'`, dev-proxy `/api` → `127.0.0.1:8000` |

Если меняешь контракт API, синхронно проверяй `api.ts`, `types.ts`,
`Devices.tsx` и соответствующий backend-роут.

## 5. Миграции и БД

| Файл | Что делает |
|---|---|
| `alembic/env.py` | стандартный env; URL берётся из настроек приложения |
| `alembic/versions/0001_init.py` | users, sessions, address_books, address_book_entries, tags, entry_tags, address_book_permissions, customers |
| `alembic/versions/0002_last_seen.py` | `address_book_entries.last_seen` |
| `alembic/versions/0003_drop_customers.py` | удаляет `customer_id` и `customers` |
| `alembic/versions/0004_discovery_and_device_info.py` | `discovered_devices`, `device_info` + индексы |

Правила и схема — `docs/project/DATA_MODEL.md`.

## 6. Скрипты

| Файл | Назначение | Ограничения |
|---|---|---|
| `scripts/start.sh` | foreground `python -m app`, pid-файл | требует `.venv/bin/python` |
| `scripts/stop.sh` | остановка нашего `python -m app` по pid/cwd, TERM→KILL | не трогает чужие процессы |
| `scripts/docker-entrypoint.sh` | генерация/переиспользование `DEVICE_SECRET`/`WEB_SECRET` | путь `/app/data/.secrets.env` |
| `scripts/dump_ab.py` | экспорт книг из RustDesk Pro/совместимого API | сеть, токен; есть redaction |
| `scripts/repro_handshake.py` | диагностика secure/plain этапов против `hbbs` | нужен protobuf и живой сервер |
| `scripts/check_keys.py` | отпечатки `id_ed25519.pub` vs client Key | не печатает приватные ключи |
| `scripts/rendezvous_pb2.py` | копия protobuf для диагностики | синхронизировать с `app/shim/rendezvous_pb2.py` |

## 7. Docker / config

| Файл | Что важно |
|---|---|
| `Dockerfile` | multi-stage: Node 22 → Python 3.13; runtime deps без `pip-audit/bandit/grpcio-tools`; non-root UID 1000; `ENTRYPOINT` + `CMD python -m app` |
| `docker-compose.yml` | ports `8000:8000`, `21116:21116`; volumes `./data`, `./keys:ro`; env-настройки; healthcheck |
| `.dockerignore` | исключает `.env`, `data/`, `logs/`, `*.db`, `frontend/dist`, `.venv`, `node_modules` |
| `config/Caddyfile.example` | диагностический TLS `:8443` + plaintext `:8080`; не production |
| `config/rustdesk-manager.service` | systemd unit, non-root, `ProtectSystem=strict`, RW только `data/`+`logs/` |
| `.env.example` | шаблон настроек без секретов |

## 8. Карта задач → файлы

| Задача | Начать с | Проверить вместе |
|---|---|---|
| Новый RustDesk-совместимый эндпоинт | `app/api/rustdesk.py` | `app/schemas/rustdesk.py`, `docs/project/API_REFERENCE.md`, живой клиент |
| Новый внутренний эндпоинт панели | `app/api/webapi.py` | `frontend/src/api.ts`, `types.ts`, `webapi` тесты/ручной smoke |
| Изменить права книги | `app/services/ab.py` | все вызовы `get_book_for_user`/`rule_for`, `rustdesk.py`, `webapi.py`, `panel.py` |
| Изменить модель/схему | `app/models/models.py` | новая миграция, `docs/project/DATA_MODEL.md`, существующая БД |
| Presence/heartbeat | `app/services/presence.py`, `app/api/rustdesk.py` | `webapi.entry_out`, `Devices.tsx`, `docs/SECURITY.md` (SEC-005) |
| Sysinfo | `app/services/device_info.py`, `app/api/rustdesk.py` | `webapi` device-info, `Devices.tsx`, миграция 0004 |
| Discovery | `app/shim/shim.py`, `app/services/discovery*.py` | `app/main.py` lifespan, `webapi`, `Devices.tsx`, `docs/knowledge/ERRORS.md` |
| KX/протокол | `app/shim/shim.py` | `scripts/repro_handshake.py`, `check_keys.py`, `docs/en.md §6,10`, живой клиент |
| UI-контракт | `frontend/src/api.ts` | `types.ts`, страница, backend |
| Запуск/деплой | `app/__main__.py`, `Dockerfile`, `docker-compose.yml` | `scripts/*`, `docs/development/WORKFLOW.md` |
| Безопасность | `app/core/*`, `app/api/deps.py`, `app/main.py` | `docs/SECURITY.md`, `SECURITY_AUDIT.md`, все пути auth |
| Логи/диагностика | `app/core/logging.py` | stdout/`docker compose logs`; файла `logs/app.log` код не создаёт |

## 9. Файлы, которые часто меняются вместе

- `app/models/models.py` + `alembic/versions/*` + `docs/project/DATA_MODEL.md`.
- `app/api/webapi.py` + `frontend/src/api.ts` + `frontend/src/types.ts` +
  соответствующая страница.
- `app/shim/shim.py` + `app/shim_supervisor.py` + `app/main.py` lifespan +
  `app/services/discovery*.py`.
- `app/core/config.py` + `.env.example` + `docker-compose.yml` +
  `docs/development/WORKFLOW.md`.
- `app/core/middleware.py` + `app/core/config.py` + `docs/project/ARCHITECTURE.md`
  + `docs/SECURITY.md` при изменении rate limiting.
- `tests/test_heartbeat_rate_limit.py` + `app/core/middleware.py` +
  `app/api/rustdesk.py` при изменении heartbeat.
- `tests/test_sysinfo_upload.py` + `app/services/device_info.py` +
  `app/api/rustdesk.py` при изменении sysinfo/refresh.
- `README.md` + `docs/ru.md` + `docs/en.md` при изменении публичного
  поведения/команд.
