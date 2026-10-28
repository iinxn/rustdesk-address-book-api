# TESTING — проверки и автотесты

## 1. Фактическое состояние

Автотесты есть только для heartbeat rate limiting и sysinfo write-once;
полного покрытия нет.

- `tests/test_heartbeat_rate_limit.py` — обычный heartbeat, 800 устройств за
  одним IP, независимые bucket'ы, реальное превышение лимита, повторные
  `429`, параллельный всплеск, chunked без `Content-Length`, сохранение
  лимитов login.
- `tests/test_sysinfo_upload.py` — первая запись, повторный upload не
  перезаписывает карточку, «достройка» неполной карточки, разрешение от
  кнопки (одноразовое), неизвестный ID не создаёт строку, discovery/книга
  создают, 800 устройств на первом старте, 800 повторных upload-ов без
  записи, конечный лимит, неизменность ответов на битые тела.
- `tests/conftest.py` поднимает временную SQLite и применяет Alembic
  `upgrade head`; `data/` не используется.
- `pytest`/`httpx` вынесены в `requirements-dev.txt`, не в runtime.
- Остальные области (auth, права книг, миграции, SPA) автотестами не
  покрыты. `.pytest_cache/` — кеш, а не доказательство покрытия.

Не заявляй «тесты пройдены», если ты их не запускал. Не добавляй фиктивный
`pytest.ini` ради зелёного отчёта.

## 2. Обязательный минимум для любого изменения

```bash
# Python: синтаксис и импорт
.venv/bin/python -m compileall -q app tests
.venv/bin/python -c 'import app.main'

# Автотесты (быстрые)
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q

# Нагрузочные сценарии heartbeat (800 устройств)
RUN_LOAD_TESTS=1 .venv/bin/python -m pytest -q -m slow

# Frontend (если менялся UI/типы/контракт)
cd frontend && npm run build && npm run lint
```

`compileall` не исполняет код; импорт `app.main` проверяет настройки,
роутеры, модели и монтирование SPA. Для изменений в миграциях добавь проверку
на копии БД (§6).

Опционально, если установлены инструменты из `requirements.txt`:

```bash
.venv/bin/pip-audit
.venv/bin/bandit -r app scripts
```

Результаты не считаются «новыми», если ты не сравнил их с базовой линией;
не скрывай найденное.

## 3. Изолированный стенд

Никогда не проверяй разрушительные сценарии на `data/base.db`. Используй
временную БД и отдельный порт:

```bash
mkdir -p /tmp/opencode/rd-test
export DEV_MODE=1
export DATABASE_URL=sqlite:////tmp/opencode/rd-test/test.db
export HOST=127.0.0.1
export PORT=18000
export SHIM_ENABLED=0
export DISCOVERY_ENABLED=0
.venv/bin/python -m app
```

`DEV_MODE=1` допускает пустые секреты; для сценариев с паролями устройств
лучше задать одноразовые значения:

```bash
export DEVICE_SECRET="$(.venv/bin/python -m app.cli gen-key)"
export WEB_SECRET="$(openssl rand -hex 32)"
```

Создай пользователя без интерактивного `getpass`:

```bash
DATABASE_URL=sqlite:////tmp/opencode/rd-test/test.db DEV_MODE=1 \
.venv/bin/python - <<'PY'
from app.db.session import SessionLocal
from app.services.auth import create_user
db = SessionLocal()
u = create_user(db, "admin", "test-password", is_admin=True)
print(u.id)
db.close()
PY
```

Для второго пользователя и shared-книги:

```bash
DATABASE_URL=sqlite:////tmp/opencode/rd-test/test.db DEV_MODE=1 \
.venv/bin/python - <<'PY'
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.models import AddressBook, AddressBookPermission, User
from app.services.auth import create_user
db = SessionLocal()
u = create_user(db, "viewer", "test-password", is_admin=False)
book = AddressBook(name="Team", type="shared", owner_user_id=db.scalar(select(User).where(User.username == "admin")).id)
db.add(book); db.flush()
db.add(AddressBookPermission(address_book_id=book.id, user_id=u.id, rule=1))
db.commit()
print(book.id)
db.close()
PY
```

Очистка после проверки: остановить процесс, удалить `/tmp/opencode/rd-test`,
не трогать `data/`, `logs/`, `.env`.

## 4. Smoke-тест API

Ниже `BASE=http://127.0.0.1:18000`. Токен извлекай без `jq`:

```bash
BASE=http://127.0.0.1:18000
TOKEN=$(curl -s -X POST "$BASE/api/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"test-password","type":"account"}' \
  | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"
```

### 4.1. Health и отказы

```bash
curl -si "$BASE/health/ready" | head -20
curl -si "$BASE/health" | head -5
curl -si "$BASE/api/ab/personal" -X POST | head -20          # 401
curl -si "$BASE/docs" | head -5                              # 404 при DEV_MODE=0
```

Ожидаемо: `200 ready`, `401 {"error":"unauthorized"}` на анонимный запрос,
`404` на docs в production-режиме.

### 4.2. Аутентификация

| Сценарий | Ожидание |
|---|---|
| верный пароль | `200`, `access_token`, `user` |
| неверный пароль | `401 {"error":"Invalid username or password"}` |
| несуществующий пользователь | тот же 401 (без раскрытия) |
| disabled-пользователь | 401 |
| `/api/currentUser` с токеном | `200`, тот же username |
| `/api/logout`, затем старый токен | `200`, затем `401` |
| смена пароля через `/api/v1/users/{uid}` | старый токен → `401` |
| disable через `/api/v1/users/{uid}` | все токены → `401` |

### 4.3. Книги и права

```bash
curl -s -X POST "$BASE/api/ab/personal" -H "$AUTH" -H 'Content-Length: 0'
curl -s -X POST "$BASE/api/ab/shared/profiles?current=1&pageSize=100" -H "$AUTH"
curl -s -X POST "$BASE/api/ab/peers?current=1&pageSize=100&ab=<book-id>" -H "$AUTH"
```

Проверь:

- личная книга возвращает `guid`;
- shared-книга видна admin и пользователю с permission; без permission —
  `404`;
- чужой personal `guid` → `404`;
- `rule=1` запрещает add/update/delete (`403 read-only`), но разрешает чтение;
- `rule=2` разрешает запись, но не rename/delete книги (нужен `rule=3`);
- admin видит все shared-книги с rule 3.

### 4.4. Устройства и ID

```bash
# добавление
curl -s -X POST "$BASE/api/ab/peer/add/<book-id>" -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{"id":"123456789","alias":"PC","tags":["work"]}'

# список
curl -s -X POST "$BASE/api/ab/peers?current=1&pageSize=100&ab=<book-id>" -H "$AUTH"

# обновление
curl -s -X PUT "$BASE/api/ab/peer/update/<book-id>" -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{"id":"123456789","alias":"PC 2","tags":["home"]}'

# удаление
curl -s -X DELETE "$BASE/api/ab/peer/<book-id>" -H "$AUTH" \
  -H 'Content-Type: application/json' -d '["123456789"]'
```

Обязательные негативные проверки:

| Вход | Ожидание |
|---|---|
| `id` с `@`, `/`, `?`, `&`, `=`, пробелом | `422 invalid id...` |
| пустой `id` | `400 missing id` |
| повторный `id` | `409 ... already exists` |
| превышение `MAX_PEER_ONE_AB` | `403 exceed_max_devices` |
| невалидный JSON | `400 bad json` |
| удаление не-массивом | `400 expected id list` |

ID с `@`/`/r` — это не косметика: клиент воспринимает их как редирект на
другой сервер/relay. Валидация обязательна.

### 4.5. Теги

- add → список содержит тег; повторный add обновляет цвет;
- rename на существующее имя → `409`;
- update несуществующего → `404`;
- delete тега удаляет `entry_tags`, но не устройства;
- `{"color":"abc"}` в RustDesk-роуте сейчас даёт `500` (SEC-004,
  известный дефект); не считай это «нормой» при новом тестировании.

### 4.6. Heartbeat и presence

```bash
curl -s -X POST "$BASE/api/heartbeat" -H 'Content-Type: application/json' \
  -d '{"id":"123456789","ver":"1.4.0"}'
```

- ответ `{}`;
- `last_seen` у записей с этим ID обновился;
- сразу после heartbeat presence `online`;
- через >45 секунд — `offline` (без нового heartbeat);
- устройство, у которого никогда не было `last_seen`, — `unknown`;
- невалидный/пустой `id` → `{}`, без изменения БД;
- heartbeat **не** создаёт `device_info` и discovered.

Подделка чужого ID работает by design (SEC-005); проверяй, что лимиты
20/мин на `(id, client IP)` и 6000/мин на IP действуют, а не пытайся
«закрыть» это без согласования.

### 4.7. Sysinfo

```bash
curl -si -X POST "$BASE/api/sysinfo" -H 'Content-Type: application/json' \
  -d '{"id":"123456789","hostname":"desk","username":"alice","os":"Windows 11 / 23H2","cpu":"Intel, 3.2GHz, 8/4 cores","memory":"16GB","version":"1.4.0","uuid":"secret","preset":{"password":"secret"}}'
```

Ожидаемо: `200 SYSINFO_UPDATED`; в `device_info` нет `uuid` и `preset`;
`os_name`/`os_version`/`cpu_model`/`memory_gb` распарсены или пусты, но не
выдуманы. Проверь:

| Вход | Ожидание |
|---|---|
| >32 KiB | `413 ID_NOT_FOUND` |
| не JSON | `400 ID_NOT_FOUND` |
| `id` с `@` | `200 ID_NOT_FOUND` |
| неизвестный, но валидный ID | `200 SYSINFO_UPDATED` (создаёт строку) |
| `sysinfo_ver` | `200 text/plain 1` |

### 4.8. `/api/v1`

```bash
curl -s "$BASE/api/v1/stats" -H "$AUTH"
curl -s "$BASE/api/v1/address-books" -H "$AUTH"
curl -s "$BASE/api/v1/address-books/<book-id>/entries?page=1&page_size=50" -H "$AUTH"
curl -s "$BASE/api/v1/address-books/<book-id>/tags" -H "$AUTH"
curl -s "$BASE/api/v1/discovered" -H "$AUTH"
curl -s "$BASE/api/v1/device-info/123456789" -H "$AUTH"
```

Проверь:

- `stats` считает только видимые книги, `discovered` — server-wide;
- `entries`: `search`, `tag` (repeat), `mode=and|or`, `untagged`,
  `presence`, `sort`, `order`, `page`, `page_size` (кап 200);
- `page_size=100000` возвращает ≤200;
- `sort` вне белого списка не ломает запрос (падает в alias);
- bulk-delete: 500 ID — ок, 501 — `400`; чужая запись → `failed: forbidden`,
  частичный успех;
- bulk-tags: add/remove, лимит 20 имён, частичный успех;
- discovered: `only_unlinked`, `status`, поиск по IP/hostname/username/os;
- device-info: `sources`, `entries[].book_id/book_name`, `online` — union
  discovery и presence; не-админ без записи/динскавери → `404`;
- refresh: `{"ok":true,"expires_in":1800}`, следующий heartbeat →
  `{"sysinfo":true}` один раз;
- users: не-админ → `403`; нельзя demote/disable/delete себя.

### 4.9. Legacy-панель

Через браузер или curl с cookie-jar:

```bash
curl -s -c /tmp/opencode/rd-test/cookies.txt -b /tmp/opencode/rd-test/cookies.txt \
  -X POST "$BASE/panel/login" -d 'username=admin&password=test-password' -i
curl -s -b /tmp/opencode/rd-test/cookies.txt "$BASE/panel/devices" | head
```

Проверь: успешный вход → 303; неверный → 401 HTML; без cookie `/panel/devices`
→ 303 на login; после disable пользователя старая cookie → 303 (SEC-001).
CSRF-токенов нет — не «тестируй» cross-site POST как поддерживаемый сценарий.

## 5. Shim: ручная проверка

Нужен живой `hbbs` и приватный ключ. Не запускай на рабочем порту
`21116`; используй временный, например `22116`, и `SHIM_UPSTREAM` на
тестовый `hbbs`.

```bash
SHIM_ENABLED=1 SHIM_LISTEN=127.0.0.1:22116 SHIM_UPSTREAM=127.0.0.1:21166 \
SHIM_ID_KEY=/path/to/id_ed25519 DISCOVERY_ENABLED=0 \
DEV_MODE=1 DATABASE_URL=sqlite:////tmp/opencode/rd-test/test.db \
.venv/bin/python -m app
```

Проверки:

| Сценарий | Ожидание |
|---|---|
| `/health/ready` | `shim.state=running`, `alive=true` |
| залогиненный клиент | в логе `secure established`, соединение работает |
| разлогиненный клиент | `plain passthrough` |
| UDP-запрос | ответ от upstream, сессия живёт ≤120 с idle |
| мусор в TCP | соединение закрыто, процесс жив |
| занятый `SHIM_LISTEN` | `address already in use`, рестарты, затем `down` |
| `.pub` вместо приватного ключа | `bad id_ed25519 length` / crash-loop |
| upstream = `21117` | соединения не работают; это relay, не rendezvous |

Для discovery включи `DISCOVERY_ENABLED=1` и проверь, что после
`register_peer` появляется строка, `online=true`, после закрытия —
`false`; после простоя >`DISCOVERY_ONLINE_SEC` — stale-sweep снимает
`online`. Очередь in-memory: при рестарте необработанные события теряются.

## 6. Миграции

Проверяй на копии, не на `data/base.db`:

```bash
cp data/base.db /tmp/opencode/rd-test/copy.db
DATABASE_URL=sqlite:////tmp/opencode/rd-test/copy.db DEV_MODE=1 \
  .venv/bin/alembic -c alembic.ini upgrade head
DATABASE_URL=sqlite:////tmp/opencode/rd-test/copy.db DEV_MODE=1 \
  .venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect('/tmp/opencode/rd-test/copy.db')
print(c.execute('PRAGMA integrity_check').fetchone()[0])
print(c.execute('SELECT version_num FROM alembic_version').fetchone())
PY
```

Затем downgrade на предыдущую ревизию и снова upgrade. Если downgrade
необратим (удаление данных), это должно быть осознанным и описанным в
миграции.

## 7. Регрессии, которые легко пропустить

При изменении затронутого кода проверь все пункты:

- **Права книг:** personal-владелец, shared с rule 1/2/3, admin, чужой
  пользователь. Проверять и чтение, и запись.
- **Приватность ответов:** `/api/ab/*` не должен внезапно начать отдавать
  `presence`, `tag_objs`, `info`, `in_books`; `/api/v1/*` — не должен терять
  поля, которые использует SPA.
- **Presence:** heartbeat обновляет все копии ID; `unknown` не превращается
  в `offline`; чтение не синтезирует `last_seen`.
- **Discovery:** `online` не управляется heartbeat; sweep работает при пустой
  очереди; строки не дублируются.
- **Sysinfo:** `uuid`/preset не сохраняются; пустые поля не выдумываются;
  ответы — ровно `SYSINFO_UPDATED`/`ID_NOT_FOUND`.
- **Сессии:** logout, expiry, disable, смена пароля, удаление пользователя.
- **Ошибки:** формат `error` vs `detail` не смешан; нет traceback.
- **Таймзоны:** все новые timestamps naive UTC; frontend `parseUtc`.
- **Миграции:** файл в git; `down_revision` = head; работает на копии.
- **Frontend:** `npm run build` + `npm run lint`; типы `api.ts`/`types.ts`
  совпадают с ответами.
- **Секреты:** в логах/ответах/документации нет ключей, токенов, паролей,
  содержимого `.env`.

## 8. Если добавляешь автотесты

Требования, чтобы не сломать рабочую среду:

- использовать `tmp_path`/временную SQLite, никогда `data/`;
- выставлять env **до** импорта `app.core.config` (settings — синглтон,
  читается при импорте); см. `tests/conftest.py`;
- не запускать реальный shim на `21116`; для протокола — unit-тесты
  кодирования/крипты без сети;
- не требовать `hbbs` для обычных тестов;
- тестовые зависимости держать в `requirements-dev.txt`, не в runtime;
- тесты не должны печатать секреты и реальные данные;
- для нагрузочных сценариев помечать тесты `slow` и запускать их осознанно
  (`RUN_LOAD_TESTS=1`), не выдавая синтетику за production-замер.

Текущий набор — `tests/test_heartbeat_rate_limit.py` и
`tests/test_sysinfo_upload.py`; расширяй их и добавляй новые файлы, сохраняя
изоляцию БД и детерминизм лимитов.
