# API_REFERENCE — контракты HTTP API

Документ описывает **фактические** маршруты, тела, коды и права. Публичные
примеры для пользователя — `docs/ru.md` / `docs/en.md`; здесь — то, что нужно
для изменения кода и диагностики.

## 1. Общие правила

### 1.1. Группы маршрутов

| Префикс | Назначение | Аутентификация | Формат ошибок |
|---|---|---|---|
| `/api/login`, `/api/login-options`, `/api/heartbeat`, `/api/sysinfo*` | контракт RustDesk-клиента | нет by design | `{"error": ...}` / `text/plain` |
| `/api/ab/*`, `/api/currentUser`, `/api/logout` | RustDesk Address Book | Bearer (кроме logout) | `{"error": ...}` |
| `/api/v1/*` | внутренний API SPA | Bearer | `{"detail": ...}` |
| `/panel/*` | legacy HTML-панель | cookie `session` | HTML/redirect 303 |
| `/health*` | health-check | нет | JSON |

`Authorization: Bearer <token>`; заголовок без префикса `Bearer ` даёт пустой
токен и `401`. Токен — opaque, хранится в `sessions`.

### 1.2. Ошибки

| Источник | Тело | Код |
|---|---|---|
| `current_user` / middleware 401 | `{"error":"unauthorized"}` | 401 |
| ручные ошибки `/api/*` | `{"error":"..."}` | 400/401/403/404/409/422 |
| ручные ошибки `/api/v1/*` | `{"detail":"..."}` | 400/403/404/409/422/500 |
| Pydantic-валидация | `{"detail":[{...}]}` | 422 |
| rate limit | `{"error":"rate limited"}` + `Retry-After` | 429 |
| body cap | `{"detail":"body too large"}` | 413 |
| `/api/sysinfo` | `text/plain` `ID_NOT_FOUND` / `SYSINFO_UPDATED` | 200/400/413 |

Важно: 401 от dependency `current_user` обрабатывается глобальным
`@app.exception_handler(401)` и для любого `/api/*` возвращает
`{"error":"unauthorized"}`, даже на `/api/v1/*`. Не удивляйся, что ручные
ошибки `/api/v1` имеют `detail`, а 401 — `error`.

Ответы не содержат traceback, SQL и путей. `/docs`, `/redoc`,
`/openapi.json` отключены, пока `DEV_MODE=1` или `EXPOSE_DOCS=1`.

### 1.3. Лимиты и размеры

| Что | Значение | Где |
|---|---|---|
| `MAX_BODY_BYTES` | 5 MiB (по `Content-Length`) | `BodyCapMiddleware` |
| `/api/sysinfo` | 32 KiB (фактическое чтение тела) | `rustdesk.sysinfo` |
| `/api/login` | 20 запросов/мин на IP | `LOGIN_PER_MINUTE_PER_IP` |
| `/api/heartbeat` | 20/мин на устройство (ключ `id` + IP) | `HEARTBEAT_PER_MINUTE_PER_DEVICE` |
| `/api/heartbeat` | 6000/мин суммарно на IP (защита от флуда) | `HEARTBEAT_PER_MINUTE_PER_IP` |
| `/api/sysinfo` | 6000/мин на IP (агрегатный потолок) | `SYSINFO_PER_MINUTE_PER_IP` |
| bulk ids | 500 уникальных | `MAX_BULK_IDS` |
| bulk tags | 20 имён, длина ≤64 | `MAX_BULK_TAGS` |
| `page_size` в `/api/v1` | 1…200 | `list_entries`, `list_discovered` |
| `pageSize` в `/api/ab/*` | **не ограничен** | SEC-006, известное ограничение |

`X-Forwarded-For` учитывается только если прямой peer входит в
`TRUSTED_PROXIES`; иначе используется прямой IP. Клиенты за одним NAT
получают общий IP, поэтому heartbeat лимитируется отдельно по устройству,
а per-IP значение — только агрегатный потолок. При `429` сервер отдаёт
`Retry-After` (секунды до освобождения окна).

### 1.4. Время

Все `*_at`, `last_seen`, `first_seen` — naive UTC в ISO 8601 **без** `Z`
(`datetime.isoformat()`). Frontend добавляет `Z` в `parseUtc`. Не меняй формат
на одной стороне.

## 2. RustDesk-совместимый API

### 2.1. `POST /api/login`

Тело (лишние поля допускаются):

```json
{
  "username": "user",
  "password": "secret",
  "id": "",
  "uuid": "",
  "autoLogin": false,
  "type": "account",
  "deviceInfo": {},
  "verificationCode": "",
  "tfaCode": "",
  "secret": ""
}
```

`type`, `verificationCode`, `tfaCode`, `secret`, `deviceInfo` принимаются, но
2FA/device-binding не реализованы.

Успех `200`:

```json
{
  "access_token": "<opaque>",
  "type": "access_token",
  "user": {
    "name": "user",
    "display_name": "",
    "avatar": "",
    "email": "",
    "note": "",
    "status": 1,
    "is_admin": false
  }
}
```

Ошибка: `401 {"error":"Invalid username or password"}` (в том числе для
disabled-пользователя — причина не раскрывается).

### 2.2. `POST /api/currentUser`

Bearer обязателен. Возвращает тот же объект `user`, но `status` = `0`, если
пользователь disabled (при этом сам запрос уже не пройдёт `user_by_token`,
так что `0` практически недостижим). `401 {"error":"unauthorized"}`.

### 2.3. `POST /api/logout`

Bearer не обязателен. Если токен передан — удаляет сессию. Всегда `200` с
пустым телом.

### 2.4. `GET /api/login-options`

Всегда `200 []`. 2FA-опций нет.

### 2.5. `POST /api/ab/settings`

Bearer. Ответ: `{"max_peer_one_ab": 0}`. `0` = без лимита.

### 2.6. `POST /api/ab/personal`

Bearer. Возвращает `{"guid": "<book id>"}`. Если личной книги нет (старые
данные), она создаётся «на лету».

### 2.7. `POST /api/ab/shared/profiles?current=1&pageSize=100`

Bearer. Возвращает shared-книги, доступные пользователю (admin — все):

```json
{
  "total": 1,
  "data": [
    {"guid": "...", "name": "Team", "owner": "<user id>", "note": "", "info": null, "rule": 2}
  ]
}
```

`current` минимум 1; `pageSize` не капается. `rule`: 1/2/3.

### 2.8. `POST /api/ab/peers?current=1&pageSize=100&ab=<guid>`

Bearer. Читает книгу, если есть доступ (personal-владелец, permission или
admin на shared). `404 {"error":"no such address book"}` иначе.

```json
{
  "total": 2,
  "data": [
    {
      "id": "123456789",
      "username": "alice",
      "hostname": "desktop",
      "platform": "Windows",
      "alias": "Office PC",
      "tags": ["work"],
      "note": "",
      "hash": "<device hash>"
    }
  ]
}
```

Для `personal`-книги в объекте есть `hash`, для `shared` — `password`
(расшифрованный). Поля `presence`, `tag_objs`, `info` сюда **не** попадают.
`pageSize` не ограничен, сортировка — по `rustdesk_id`; N+1 по тегам
(SEC-006).

### 2.9. `POST /api/ab/peer/add/{guid}`

Bearer + `can_write` (`rule >= 2`). Тело — произвольный JSON:

```json
{
  "id": "123456789",
  "alias": "Office PC",
  "note": "",
  "username": "alice",
  "hostname": "desktop",
  "platform": "Windows",
  "hash": "...",
  "password": "...",
  "tags": ["work"]
}
```

Правила:

- `id` валидируется; `missing id` → 400, прочие ошибки ID → 422;
- дубликат в книге → `409 {"error":"<id> already exists"}`;
- превышение `MAX_PEER_ONE_AB` → `403 {"error":"exceed_max_devices"}`;
- для personal сохраняется `hash`, для shared — `password` (Fernet);
- `tags` заменяют набор, отсутствующие теги создаются с `color=0`;
- успех — `200` с пустым телом.

### 2.10. `PUT /api/ab/peer/update/{guid}`

Bearer + write. Тело с `id` (обязателен). Обновляются только строковые поля
`alias`, `note`, `username`, `hostname`, `platform`, `hash` (personal),
`password` (shared) и `tags` (полная замена). `id` изменить нельзя — для
смены ID используй `/api/v1/entries/{eid}`.

`404 not found`, `400 missing id`, `403 read-only`, `200` пусто.

### 2.11. `DELETE /api/ab/peer/{guid}`

Bearer + write. Тело — JSON-массив ID:

```json
["123456789", "987654321"]
```

Удаляет найденные записи; отсутствующие молча игнорирует. `200` пусто.
`400 expected id list`, если передан не массив.

### 2.12. Теги книги

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| POST | `/api/ab/tags/{guid}` | — | `[{"name":"work","color":4294901760}]` |
| POST | `/api/ab/tag/add/{guid}` | `{"name":"work","color":...}` | `200` пусто; upsert (существующий цвет обновляется) |
| PUT | `/api/ab/tag/rename/{guid}` | `{"old":"a","new":"b"}` | `200`; `409`, если `b` уже есть |
| PUT | `/api/ab/tag/update/{guid}` | `{"name":"a","color":...}` | `200`; `404`, если нет |
| DELETE | `/api/ab/tag/{guid}` | `["a","b"]` | `200`; связи `entry_tags` каскадны |

Все требуют доступа к книге; изменяющие — `can_write`. `color` приводится
через `int(...)` без валидации диапазона: нечисловое значение даёт 500
(SEC-004, известное ограничение).

### 2.13. `POST /api/heartbeat`

Без auth. Тело — объект; клиент шлёт `{"id","uuid","ver",...}` каждые 15 с.

- Валидный `id` → `last_seen=now` для всех записей с этим ID во всех книгах;
  если для ID уже есть `device_info`, обновляются `last_heartbeat_at`, `ver`,
  `ip`.
- Если выставлен флаг refresh → ответ `{"sysinfo": true}` (один раз).
- Иначе, а также при невалидном теле/ID → `{}`.

Флаг refresh (кнопка «Refresh info» в панели) — единственный способ
разрешить перезапись уже заполненной карточки. Heartbeat, отдавший
`{"sysinfo": true}`, выдаёт одноразовое разрешение на 120 секунд; клиент
обычно присылает `/api/sysinfo` в течение ~3 секунд.

Heartbeat **не** создаёт `device_info` и **не** создаёт discovered. Подделка
ID возможна by design (SEC-005, accepted risk). Защита от флуда двухслойная:
20/мин на пару `(id, client IP)` и 6000/мин суммарно на IP; запрос без
валидного `id` (в т.ч. chunked без `Content-Length`) ограничивается только
агрегатным IP-потолком. При `429` — `{"error":"rate limited"}` и
`Retry-After`. DB-работа выполняется в threadpool, чтобы всплеск heartbeat
не блокировал event loop.

### 2.14. `POST /api/sysinfo_ver`

Без auth. `text/plain` `1`, `Cache-Control: no-store`.

### 2.15. `POST /api/sysinfo`

Без auth. Тело — JSON-объект от штатного клиента:

```json
{
  "id": "123456789",
  "hostname": "desktop",
  "username": "alice",
  "os": "Windows 11 / 23H2",
  "cpu": "Intel..., 3.2GHz, 8/4 cores",
  "memory": "16GB",
  "version": "1.4.0",
  "uuid": "..."
}
```

Поведение:

| Условие | Ответ |
|---|---|
| тело > 32 KiB | `413` `ID_NOT_FOUND` |
| не JSON / не объект | `400` `ID_NOT_FOUND` |
| невалидный/пустой `id` | `200` `ID_NOT_FOUND` |
| `id` валиден и лимит не превышен | `200` `SYSINFO_UPDATED` |
| превышен `SYSINFO_PER_MINUTE_PER_IP` | `429` `{"error":"rate limited"}` + `Retry-After` |

`SYSINFO_UPDATED` возвращается и тогда, когда запись намеренно пропущена:
клиент считает любую другую строку временной ошибкой и повторяет отправку
каждые ~2 минуты (а на `ID_NOT_FOUND` — каждые 3 секунды). Поэтому
«принято, но не записано» — это штатный ответ, а не ошибка.

Когда строка **не** пишется:

- карточка уже заполнена (`hostname`, `os`, `username`), и нет разрешения
  от кнопки панели. Автоматическая перезапись существующей карточки
  отключена: клиент сам шлёт sysinfo при старте и после входа пользователя
  Windows, и иначе весь парк переписывал бы БД при каждом рестарте;
- строка неполная, но в payload нет недостающих полей (например, пустой
  `username`): разрешается только «достроить» карточку, а не переписывать её;
- `id` валиден, но устройство неизвестно панели: его нет ни в
  `address_book_entries`, ни в `discovered_devices`. Строка не создаётся,
  чтобы поток случайных ID не раздувал БД. Добавь устройство в книгу и
  нажми «Refresh info»;
- запрос отклонён лимитом (`429`).

Разрешение от кнопки (`force`) обходит эти проверки один раз, поэтому
работает и для неполной карточки, и для устройства, которого ещё нет в книге
(если у пользователя есть доступ к его карточке).

Ответ всегда `text/plain`, `Cache-Control: no-store`. Whitelist полей:
`hostname`, `username`, `os`, `cpu`, `memory`, `version`, `ip`; `uuid` и все
preset/option-ключи (могут содержать пароли книг) отбрасываются. Парсинг
CPU/RAM/OS консервативный: не распознал — поле пустое. Запись выполняется в
threadpool со своей сессией, чтобы первый старт парка не блокировал event
loop.

### 2.16. Legacy-заглушки

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/api/ab` | `null` (JSON) |
| POST | `/api/ab` | `200` пусто |
| GET | `/api/device-group/accessible` | `{"total":0,"data":[]}` |
| GET | `/api/users` | `{"total":0,"data":[]}` |
| GET | `/api/peers` | `{"total":0,"data":[]}` |

Все требуют Bearer. Это «тишилки» для клиента; групп устройств и глобального
списка peers нет.

## 3. Внутренний API панели `/api/v1`

Все маршруты требуют Bearer. Ошибки — `{"detail": ...}`, кроме 401
(см. §1.2). Доступ к книгам проверяется через `get_book_for_user` /
`rule_for` на каждом запросе.

### 3.1. `GET /api/v1/stats`

```json
{
  "devices": 451,
  "online": 3,
  "offline": 20,
  "unknown": 428,
  "discovered": 5,
  "discovered_online": 1
}
```

`devices`/presence считаются по видимым книгам; `discovered` — по всей
таблице `discovered_devices`, независимо от книг (server-wide evidence).

### 3.2. Книги

| Метод | Путь | Права | Тело | Ответ |
|---|---|---|---|---|
| GET | `/api/v1/address-books` | видимые | — | массив книг |
| POST | `/api/v1/address-books` | admin | `{"name":"Team"}` | `{"id","name","type":"shared"}` |
| PUT | `/api/v1/address-books/{bid}` | shared + `rule>=3` | `{"name":"New"}` | `{"id","name","type"}` |
| DELETE | `/api/v1/address-books/{bid}` | shared + `rule>=3` | — | `{"ok":true}` |

`GET` возвращает:

```json
[
  {
    "id": "...",
    "name": "My address book",
    "type": "personal",
    "rule": 3,
    "devices": 12,
    "online": 1,
    "offline": 2,
    "unknown": 9
  }
]
```

Личную книгу нельзя переименовать/удалить через эти маршруты (`400`).

### 3.3. `GET /api/v1/address-books/{bid}/entries`

Query:

| Параметр | Значение | По умолчанию |
|---|---|---|
| `search` | подстрока по ID, alias, note, hostname, username, а также sysinfo hostname/username/os | `""` |
| `tag` | повторяемый параметр | `[]` |
| `mode` | `or` \| `and` | `or` |
| `untagged` | bool | `false` |
| `presence` | `all` \| `online` \| `offline` \| `unknown` | `all` |
| `sort` | `alias` \| `rustdesk_id` \| `last_seen` \| `status` | `alias` |
| `order` | `asc` \| `desc` | `asc` |
| `page` | ≥1 | `1` |
| `page_size` | 1…200 | `50` |

Ответ:

```json
{
  "total": 12,
  "data": [
    {
      "id": "<entry uuid>",
      "rustdesk_id": "123456789",
      "alias": "Office PC",
      "note": "",
      "tags": ["work"],
      "tag_objs": [{"id": "...", "name": "work", "color": 4294901760}],
      "presence": "online",
      "last_seen": "2026-10-25T10:00:00",
      "password_configured": true,
      "hostname": "desktop",
      "username": "alice",
      "platform": "Windows",
      "ip": "203.0.113.10",
      "os": "Windows 11",
      "has_info": true,
      "info_updated_at": "2026-10-25T09:00:00",
      "created_at": "2026-10-01T08:00:00",
      "updated_at": "2026-10-25T10:00:00"
    }
  ]
}
```

`hostname`/`username` берутся из записи книги, а при пустом значении — из
`device_info`; `ip`/`os`/`has_info`/`info_updated_at` — только из sysinfo.
`last_seen` — heartbeat-время, не discovery.

### 3.4. `POST /api/v1/address-books/{bid}/entries`

Тело `EntryIn`:

```json
{
  "rustdesk_id": "123456789",
  "alias": "Office PC",
  "note": "",
  "tags": ["work"],
  "password": "optional"
}
```

Требует `can_write`. `rustdesk_id` валидируется (422), дубликат — 409.
`password` шифруется, если передан. `tags` заменяют набор. Ответ — один
`entry_out` (без `DeviceInfo`, поэтому `has_info=false` до следующего чтения).
Лимит `MAX_PEER_ONE_AB` здесь **не** проверяется (в отличие от
`/api/ab/peer/add` и `/api/v1/discovered/{rid}/add`).

### 3.5. `GET|PUT|DELETE /api/v1/entries/{eid}`

- `GET` — доступ к книге записи; иначе `404 not found` (не 403, чтобы не
  раскрывать существование чужой записи).
- `PUT` — `can_write`; тело `EntryIn`. `alias`/`note` заменяются, `password`
  меняется только если непустой, `rustdesk_id` можно изменить (валидация +
  проверка дубликата), `tags` заменяются.
- `DELETE` — `can_write`; `{"ok":true}`.

### 3.6. Bulk-операции

`POST /api/v1/entries/bulk-delete`

```json
{"ids": ["<uuid>", "<uuid>"]}
```

До 500 уникальных ID. Для каждого проверяются формат UUID, существование и
`can_write`. Частичный успех:

```json
{
  "deleted": ["..."],
  "failed": [{"id": "...", "error": "invalid id|not found|forbidden"}]
}
```

`POST /api/v1/entries/bulk-tags`

```json
{"ids": ["..."], "add": ["work"], "remove": ["old"]}
```

Сначала remove, затем add (если имя в обоих списках — add побеждает).
Ответ: `{"updated":[...],"failed":[...],"added":[...],"removed":[...]}`.
Теги создаются автоматически; удаление тега с записи не удаляет сам тег.

Оба маршрута возвращают `400`, если ID больше 500 или (для tags) нет валидных
имён; `500` при ошибке commit (rollback выполняется).

### 3.7. Теги

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| GET | `/api/v1/address-books/{bid}/tags` | — | `[{"id","name","color","devices"}]` |
| POST | `/api/v1/address-books/{bid}/tags` | `{"name":"work","color":0}` | `{"id","name","color","devices":0}` |
| PUT | `/api/v1/tags/{tid}` | `{"name":"new","color":0}` | `{"id","name","color"}` |
| DELETE | `/api/v1/tags/{tid}` | — | `{"ok":true}` |
| PUT | `/api/v1/entries/{eid}/tags/{tid}` | — | `{"ok":true}` |
| DELETE | `/api/v1/entries/{eid}/tags/{tid}` | — | `{"ok":true}` |

Требуют доступ к книге; изменяющие — `can_write`. Дубликат имени — 409.
Attach требует, чтобы entry и tag были в одной книге. Detach идемпотентен.

### 3.8. `GET /api/v1/discovered`

Query: `search`, `status` (`all|online|offline`), `page`, `page_size`
(1…200), `only_unlinked` (`0|1`).

```json
{
  "total": 5,
  "data": [
    {
      "rustdesk_id": "123456789",
      "first_seen": "2026-10-20T10:00:00",
      "last_seen": "2026-10-25T10:00:00",
      "last_connected": "2026-10-25T09:59:00",
      "last_disconnected": null,
      "last_ip": "203.0.113.10",
      "source": "tcp",
      "online": true,
      "seen_count": 4,
      "in_books": [{"id": "...", "name": "Team"}],
      "info": {"rustdesk_id": "...", "hostname": "...", "...": "..."} 
    }
  ]
}
```

`only_unlinked=1` исключает ID, которые есть в **видимых** книгах; если
видимых книг нет, фильтр не применяется. `info` — полный `info_out` или
`null`.

### 3.9. `POST /api/v1/discovered/{rid}/add`

Тело `DiscoveredAddIn`:

```json
{"book_id": "...", "alias": "", "note": "", "tags": ["work"]}
```

Требует `can_write` в книгу. Валидирует ID (422), дубликат (409), лимит книги
(403 `exceed_max_devices`). Alias по умолчанию — hostname из sysinfo или сам
ID. Ответ — `entry_out`.

### 3.10. `GET /api/v1/device-info/{rid}`

Мержит три источника. Доступ: admin, либо ID есть в `discovered_devices`,
либо есть запись в видимой книге; иначе `404`.

```json
{
  "rustdesk_id": "123456789",
  "online": true,
  "last_seen": "2026-10-25T10:00:00",
  "last_ip": "203.0.113.10",
  "discovered": { "...": "..." },
  "info": { "...": "..." },
  "entries": [
    {"id": "...", "book_id": "...", "book_name": "Team", "...": "entry_out fields"}
  ],
  "sources": ["discovery", "sysinfo", "address_book"]
}
```

`online` = discovery online **или** presence хотя бы одной записи. `last_seen`
— максимум доступных timestamps. `sources` содержит только реально
присутствующие источники.

### 3.11. `POST /api/v1/device-info/{rid}/refresh`

Просит клиента прислать sysinfo на следующем heartbeat. Та же проверка
доступа, что в §3.10. Ответ `{"ok":true,"expires_in":1800}`. Флаг живёт в
памяти процесса 30 минут, одноразовый, работает только если клиент вообще
шлёт heartbeat (нужен custom `api-server`). Когда heartbeat забирает флаг,
он выдаёт одноразовое разрешение на запись ещё на 120 секунд — этого хватает
клиенту (~3 с), но не хватает «запоздавшему» запросу перезаписать карточку
позже. Это единственный путь перезаписать уже заполненную карточку
(см. §2.15).

### 3.12. `DELETE /api/v1/discovered/{rid}`

Только admin. Удаляет строку discovery; книги и `device_info` не трогает.
`{"ok":true}`.

### 3.13. Пользователи (admin only)

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| GET | `/api/v1/users` | — | `[{"id","username","is_admin","is_disabled"}]` |
| POST | `/api/v1/users` | `{"username","password","is_admin":false}` | `{"id","username","is_admin","is_disabled"}` |
| PUT | `/api/v1/users/{uid}` | любые из `username`, `is_admin`, `is_disabled`, `password` | тот же объект |
| DELETE | `/api/v1/users/{uid}` | — | `{"ok":true}` |

Правила: нельзя снять admin с себя, нельзя disable себя, нельзя удалить себя.
Disable или смена пароля отзывают **все** Bearer-сессии пользователя. При
создании автоматически создаётся личная книга. Удаление пользователя
каскадно удаляет его книги, сессии и permissions (и, следовательно, его
entries/tags).

## 4. Legacy-панель `/panel/*`

Cookie-сессия `session` (Starlette `SessionMiddleware`, подпись `WEB_SECRET`,
`SameSite=Lax`, `https_only=False`, срок по умолчанию 14 дней). CSRF-токенов
нет (SEC-016). `panel_user` проверяет `is_disabled` и очищает cookie.

| Метод | Путь | Что делает |
|---|---|---|
| GET | `/panel/login` | HTML-форма входа |
| POST | `/panel/login` | form `username`, `password`; успех → 303 `/panel/devices` |
| GET | `/panel/logout` | очищает cookie → 303 `/panel/login` |
| GET | `/panel/` | 303 `/panel/devices` |
| GET | `/panel/devices` | список устройств; query `book`, `search`, `tag` (repeat), `mode`, `untagged` |
| POST | `/panel/devices/create` | form `book`, `rustdesk_id`, `alias`, `note`, `tags` (через запятую), `password` |
| POST | `/panel/devices/{eid}/delete` | удаляет запись при наличии прав |
| GET | `/panel/tags` | теги книги (`book`) |
| POST | `/panel/tags/create` | form `book`, `name`, `color` |
| POST | `/panel/tags/{tid}/update` | form `name`, `color` |
| POST | `/panel/tags/{tid}/delete` | удаляет тег |
| GET | `/panel/users` | admin only, иначе 303 на devices |
| POST | `/panel/users/create` | form `username`, `password`, `is_admin` |
| POST | `/panel/users/{uid}/delete` | admin, нельзя удалить себя |

Все POST возвращают 303 (PRG). Ошибки прав чаще всего выглядят как редирект
без изменения данных, а не как JSON-ошибка. Панель не является основным UI;
новые функции добавляй в SPA, а не сюда.

## 5. Служебные маршруты

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/` | 303 `/app/` |
| GET | `/health` | `{"ok":true}` |
| GET | `/health/live` | `{"status":"live"}` |
| GET | `/health/ready` | 200 `{"status":"ready","db":"up","shim":{"state":"disabled"}}` или 503 |
| GET | `/app/` | SPA из `frontend/dist`, если каталог существует |
| GET | `/docs`, `/redoc`, `/openapi.json` | только при `DEV_MODE=1` или `EXPOSE_DOCS=1`, иначе 404 |

`/health/ready` проверяет `SELECT 1`. Если шим включён и его состояние
`down` (после >5 падений за 600 с), возвращается
`503 {"status":"not-ready","shim":{...}}`; API при этом продолжает работать.

## 6. Чего в API нет

- CORS-middleware (SPA same-origin).
- WebSocket, relay, WebRTC, удалённых сессий.
- 2FA/TFA, verificationCode, привязки к устройству.
- Групп устройств (только заглушки).
- API управления `address_book_permissions` (правилами shared-книг).
- Audit log.
- Публичного `/metrics`.
- Автоматической очистки `discovered_devices`/`device_info`.

## 7. Проверка контракта

Автотесты покрывают только heartbeat rate limiting и sysinfo write-once.
После изменения API выполни ручной smoke из `docs/development/TESTING.md`:
login → `/api/ab/personal` → `/api/ab/peers` → `/api/v1/address-books` →
нужный сценарий. Для RustDesk-контракта обязательна проверка живым клиентом:
формы ответов нельзя считать «очевидными».
