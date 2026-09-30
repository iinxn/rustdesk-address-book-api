# Web Panel (React SPA)

Новая панель: React 19 + Vite 7 + TypeScript + Tailwind CSS 4 + react-router-dom.
Исходники: `frontend/src/` (`pages/`, `components.tsx`, `api.ts`, `hooks.ts`, `types.ts`).
Старая Jinja-панель оставлена как fallback на `/panel/*`.

## Запуск

Backend (терминал 1):

```bash
cd /home/user/Documents/rustdesk-ab-backend
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Frontend dev (терминал 2, `/api` проксируется на `:8000` через `vite.config.ts`):

```bash
export PATH="$HOME/.local/node/bin:$PATH"  # node 22 ставится без sudo, см. ниже
cd frontend && npm install && npm run dev   # -> http://localhost:5173/
```

Production-сборка (её раздаёт сам backend на `/app/`, корень `/` редиректит туда):

```bash
cd frontend && npm run build   # -> frontend/dist/ (в .gitignore, собирать после clone)
```

Установка node без sudo (один раз):

```bash
mkdir -p ~/.local/node
curl -o /tmp/node.tar.xz https://nodejs.org/dist/v22.20.0/node-v22.20.0-linux-x64.tar.xz
tar -xJf /tmp/node.tar.xz -C ~/.local/node --strip-components=1
export PATH="$HOME/.local/node/bin:$PATH"
```

## Экраны

- `/app/` Devices: поиск (debounce 250мс), фильтр по тегам + AND/OR, фильтр
  presence (online/offline/unknown) и клиента, сортировка (Status+Alias по
  умолчанию), пагинация 50/стр, summary `Devices/Online/Offline`, drawer
  деталей, add/edit модалка с tag-multiselect, delete с подтверждением.
- `/app/#/books` — книги с counts; создание shared-книг (admin).
- `/app/#/tags` — таблица Name/Color/Devices, create/rename/color/delete.
- `/app/#/customers` — таблица с counts, CRUD, клик → устройства клиента.
- `/app/#/users` (admin) — CRUD, роль/статус toggle, смена пароля, защита от
  self-delete/self-disable/self-demote.
- Light/dark toggle в шапке (localStorage), тосты, loading/error/empty states.

## Используемые API (`/api/v1/*`, Bearer token в localStorage)

`GET /stats`, `GET/POST /address-books`, `GET/POST /address-books/{id}/entries`
(`search, tag[], mode, untagged, customer_id, presence, sort, order, page, page_size`),
`GET/PUT/DELETE /entries/{id}`, `PUT/DELETE /entries/{id}/tags/{tag}`,
`GET/POST /address-books/{id}/tags`, `PUT/DELETE /tags/{id}`,
`GET/POST/PUT/DELETE /customers*`, `GET/POST/PUT/DELETE /users*`.
Auth: `POST /api/login`. RustDesk-совместимые `/api/ab/*` панелью НЕ используются
и не менялись.

## Online / last_seen — откуда берётся (честно)

- Реального realtime-online у API-сервера нет: online в RustDesk определяет
  **rendezvous-сервер** (`query_online_states`), клиент его у `/api` не спрашивает.
- Реальный источник для нас: контролируемые устройства шлют
  `POST /api/heartbeat {"id","uuid","ver",...}` каждые 15 сек **только если**
  в клиенте задан кастомный (не public) api-server (`src/hbbs_http/sync.rs`).
  `PresenceService.record_heartbeat` штампует `last_seen` всем entries с этим
  `rustdesk_id`; `online` = `last_seen` свежее 45 сек.
- Никогда не виденное устройство: `presence=unknown`, UI показывает
  «Last seen — Unknown», а не выдуманный Online.
- Статус в списке тихо обновляется каждые 20 сек (повтор запроса страницы).
- Будущая интеграция: опрос hbbs (его БД/API peers) для настоящего online —
  точка входа `app/services/presence.py::status_of`, контракт `/api/v1`
  (`presence`, `last_seen`) уже готов и не изменится.
