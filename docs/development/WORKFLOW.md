# WORKFLOW — запуск, сборка, эксплуатация

Все команды — из корня репозитория, если не указано иное. Порт по умолчанию
`8000` (>1024, root не нужен). Приложение слушает `HOST:PORT`; TLS
терминируется прокси, сам процесс отдаёт HTTP.

## 1. Фактическое состояние окружения

- Python 3.13, зависимости ставятся из `requirements.txt` (без lock-файла).
- `.venv/` — локальное окружение; `.venv/bin/python` может быть симлинком на
  системный `python3`.
- Node.js 22 нужен только для сборки SPA; `frontend/package-lock.json`
  фиксирует npm-дерево.
- **Тестов нет** (см. `docs/development/TESTING.md`).
- **Docker-файлы не в git.** `Dockerfile`, `docker-compose.yml` и
  `.dockerignore` существуют в рабочем каталоге, но перечислены в
  `.gitignore`. Свежий клон репозитория их не содержит. Если Docker-деплой
  нужен, эти файлы надо добавить в git (и убрать из `.gitignore`) — иначе
  `docker compose build` на чистой машине невозможен.
- `data/app.pid` может быть протухшим: `stop.sh` это проверяет, но не
  доверяй файлу вручную.

## 2. Нативный запуск

### 2.1. Первичная установка

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Сгенерируй секреты и впиши в `.env`:

```bash
.venv/bin/python -m app.cli gen-key      # DEVICE_SECRET (Fernet key)
openssl rand -hex 32                      # WEB_SECRET
chmod 600 .env
```

`DEVICE_SECRET` шифрует пароли устройств. Его потеря/смена делает
существующие `password_encrypted` нечитаемыми. `WEB_SECRET` подписывает
cookie legacy-панели; его смена разлогинивает `/panel/`, но не Bearer-сессии.

### 2.2. Запуск

```bash
./scripts/start.sh
# или напрямую, чтобы видеть все стадии:
.venv/bin/python -m app
```

Порядок: проверка секретов (fail-fast) → создание `data/`, `logs/` и
`chmod 700`/`600` → `alembic upgrade head` → Uvicorn → (если
`SHIM_ENABLED=1`) супервизор шима → (если `DISCOVERY_ENABLED=1`) drain-задача.

`scripts/start.sh` пишет `data/app.pid` и запускает процесс в foreground.
Ctrl+C / SIGTERM останавливает всё; `data/app.pid` удаляется trap'ом.

### 2.3. Первый администратор

Второй терминал, пока сервер работает:

```bash
.venv/bin/python -m app.cli create-admin
```

Пароль вводится через `getpass` и не печатается. Пользователь создаётся
вместе с личной книгой.

### 2.4. Проверка

```bash
curl -s http://127.0.0.1:8000/health/ready
curl -s http://127.0.0.1:8000/health
ss -tlnp | grep -E ':8000|:21116'
```

Ожидаемо: `{"status":"ready","db":"up","shim":{"state":"disabled"}}`.
Панель: `http://127.0.0.1:8000/app/`. Legacy: `/panel/`.
Интерактивные docs доступны только при `DEV_MODE=1` или `EXPOSE_DOCS=1`.

### 2.5. Остановка

```bash
./scripts/stop.sh
```

Скрипт доверяет `data/app.pid` только если PID жив и это действительно
`python -m app` из этого каталога; иначе ищет процесс по cwd и проверяет,
что он исчез. Для foreground-запуска достаточно Ctrl+C.

## 3. Frontend

```bash
cd frontend
npm ci
npm run dev      # Vite на :5173, проксирует /api на 127.0.0.1:8000
npm run build    # tsc -b && vite build -> frontend/dist
npm run lint     # oxlint
```

- `base: '/app/'`, поэтому SPA доступен по `/app/`.
- FastAPI монтирует `frontend/dist` только если каталог существовал **на
  момент импорта** `app.main`. Если ты собрал SPA после старта сервера и
  `/app/` отдаёт 404 — перезапусти приложение.
- `frontend/dist` в git не хранится; Docker собирает его в отдельном stage.
- При изменении контракта синхронно правь `src/api.ts`, `src/types.ts` и
  backend-роут.

## 4. Docker

> Сейчас `Dockerfile`/`docker-compose.yml` не отслеживаются git (см. §1).
> Команды ниже работают только в каталоге, где эти файлы есть.

```bash
mkdir -p data keys && chmod 700 data
# только если SHIM_ENABLED=1:
cp /path/to/hbbs-id_ed25519 keys/ && chmod 600 keys/id_ed25519
chown -R $(id -u):$(id -g) data     # образ работает как UID 1000

docker compose up -d --build
docker compose logs -f              # ждать "migrations ok"
curl -s http://127.0.0.1:8000/health/ready
```

Особенности:

- Entrypoint генерирует `DEVICE_SECRET`/`WEB_SECRET`, если они пустые или
  `CHANGEME*`, и сохраняет их в `/app/data/.secrets.env` (mode 600).
  Явно заданные значения всегда выигрывают. Секреты не печатаются.
- Публикуются `8000` (API+SPA) и `21116` (шим, TCP/UDP). Порт `21114` **не**
  публикуется. Если клиент вычисляет API как `rendezvous_port - 2 = 21114`,
  ему нужен явный `api-server` в настройках или маппинг `21114:8000`.
- `./data` монтируется в `/app/data`; без volume БД исчезнет вместе с
  контейнером. Если исторические данные лежат в `pc-service.db`, задай
  `DATABASE_URL=sqlite:////app/data/pc-service.db`, иначе контейнер создаст
  пустой `base.db`.
- `./keys` монтируется read-only; `SHIM_ID_KEY` должен указывать на путь
  внутри контейнера (`/app/keys/id_ed25519`).
- Контейнер работает non-root (UID 1000). Если UID хоста другой — задай
  `user: "UID:GID"` или сделай `chown` на `data/`.
- Остановка: `docker compose down` (данные на хосте остаются).
- Админ: `docker compose exec app python -m app.cli create-admin`.
- Логи: `docker compose logs -f app`; файла `logs/app.log` внутри нет.

## 5. systemd

Пример: `config/rustdesk-manager.service`. Он предполагает:

- код в `/opt/rustdesk-manager`, пользователь `rustdesk`;
- `.env` через `EnvironmentFile`;
- `ProtectSystem=strict`, RW только `data/` и `logs/`;
- `Restart=on-failure`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rustdesk-manager
sudo systemctl status rustdesk-manager
journalctl -u rustdesk-manager -f
```

Права: `.env` — `600`, владелец — сервисный пользователь; `data/` — `700`.
Не запускай сервис от root без необходимости.

## 6. Reverse proxy и TLS

Приложение само TLS не делает. Для доступа извне:

1. Поставь Caddy/Nginx с валидным сертификатом.
2. Проксируй на `127.0.0.1:8000`; наружу не публикуй `8000` напрямую.
3. Если нужны корректные per-IP лимиты, задай `TRUSTED_PROXIES` (например,
   `127.0.0.1`) — только тогда `X-Forwarded-For` учитывается.
4. `config/Caddyfile.example` — **диагностический** пример: он содержит и
   HTTPS `:8443`, и plaintext `:8080`. Для production plaintext-блок нужно
   убрать (SEC-009).

Legacy-cookie получает `Secure` автоматически на HTTPS-запросах
(`SESSION_COOKIE_SECURE=auto`). За прокси это работает, если прокси шлёт
`X-Forwarded-Proto` и подключается с loopback (uvicorn доверяет
`127.0.0.1`/`::1`). Только HTTPS-доступ к панели — `SESSION_COOKIE_SECURE=1`;
панель по plain HTTP внутри VPN — `auto` или `0`.

## 7. Shim

Шим нужен только для secure rendezvous залогиненных клиентов. Требования:

- приватный 64-байтный `id_ed25519` от `hbbs` (не `.pub`);
- `hbbs` освобождает `21116` (например, `hbbs -p 21166`);
- `SHIM_UPSTREAM` указывает на **rendezvous** `hbbs`, не на relay `21117`.

`.env`:

```dotenv
SHIM_ENABLED=1
SHIM_LISTEN=0.0.0.0:21116
SHIM_UPSTREAM=127.0.0.1:21166
SHIM_ID_KEY=/abs/path/to/id_ed25519
SHIM_MAX_CONNS=200
SHIM_PER_IP_PER_MIN=30
# UDP rendezvous: ~1 сессия на устройство, отдельно от TCP
SHIM_UDP_MAX_SESSIONS=2048
SHIM_UDP_PER_IP_PER_MIN=600
```

Каждая UDP-сессия держит сокет: при systemd проверь `LimitNOFILE` (шим
поднимает soft-лимит сам, но не выше hard).

Проверка:

```bash
curl -s http://127.0.0.1:8000/health/ready   # shim.state=running, alive=true
ss -tlnp | grep 21116
ss -ulnp | grep 21116
```

В логах ищи `secure established` (залогиненный клиент) и
`plain passthrough` (разлогиненный). Отпечатки ключей можно сверить:

```bash
.venv/bin/python scripts/check_keys.py
```

Скрипт печатает только хеши, не ключи. Диагностика протокола:
`scripts/repro_handshake.py` (нужен живой `hbbs` и protobuf).

## 8. Диагностика

Порядок: **код возврата/текст ошибки → `/health/ready` → порты → конфиг →
логи → БД**.

```bash
# health и версия ответа
curl -i http://127.0.0.1:8000/health/ready

# кто слушает порты
ss -tlnp | grep -E ':8000|:21114|:21116'
ss -ulnp | grep 21116

# процесс и cwd
ps -eo pid,user,cmd | grep -E 'python -m app|uvicorn' | grep -v grep
readlink -f /proc/<pid>/cwd

# миграции (нужны валидные секреты в окружении)
.venv/bin/alembic -c alembic.ini current
.venv/bin/alembic -c alembic.ini history

# целостность SQLite (без sqlite3 CLI)
.venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect('data/base.db')
print(c.execute('PRAGMA integrity_check').fetchone()[0])
print(c.execute('SELECT version_num FROM alembic_version').fetchone())
PY
```

Логи приложения идут в **stdout/stderr**. Файла `logs/app.log` код не
создаёт: каталог `logs/` создаётся, но handler'а нет. Для systemd смотри
`journalctl`, для Docker — `docker compose logs`, для foreground — терминал.

Типовые причины:

| Симптом | Что проверить |
|---|---|
| `FATAL: DEVICE_SECRET is not set` | `.env`, `DEV_MODE`, права; не печатай значение |
| `No module named app` | запуск не из корня; используй `start.sh` |
| `address already in use` | второй инстанс/`hbbs` на `21116`; `ss -tlnp` |
| `Cannot assign requested address` | `SHIM_LISTEN` указывает на чужой IP; bind только на локальный интерфейс |
| `bad id_ed25519 length` | передан `.pub` вместо приватного ключа |
| shim `down` в `/health/ready` | >5 падений за 600 с; смотри причину в логах |
| `Failed to secure tcp: deadline has elapsed` | клиент не прошёл KX: шим выключен/не на том порту/upstream не rendezvous/ключ не тот |
| `ResolutionError: No such revision` в Docker | файл миграции не попал в образ (не закоммичен/не скопирован) |
| панель пустая после Docker | `DATABASE_URL` указывает не на тот SQLite-файл |
| login `429` | сработал лимит 20/мин на IP; подожди минуту |
| `413 body too large` | `MAX_BODY_BYTES`; для `/api/sysinfo` — 32 KiB |

## 9. Обслуживание

```bash
# backup SQLite (integrity_check + mode 600)
.venv/bin/python -m app.cli backup
.venv/bin/python -m app.cli backup --dest /safe/base-$(date +%F).db

# выгрузка книги без секретов (password/hash -> <set>/<empty>)
.venv/bin/python -m app.cli dump-book <book-id>

# создать админа
.venv/bin/python -m app.cli create-admin
```

Восстановление и правила миграций — `docs/project/DATA_MODEL.md` §6–7.

Ротация секретов:

- `WEB_SECRET` — разлогинивает legacy-панель; Bearer-сессии живут в БД и
  переживут смену.
- `DEVICE_SECRET` — **не ротируй без плана**: старые `password_encrypted`
  станут нечитаемыми (`decrypt_password` вернёт `""`). Сначала расшифруй и
  перешифруй данные или прими потерю паролей.
- `.secrets.env` в Docker — источник автосгенерированных значений; удаление
  файла при пустых env приведёт к новым секретам и тем же последствиям.

Сброс rate-limit — только перезапуск процесса: `HITS` хранится в памяти.

## 10. Что не делать

- Не запускать второй экземпляр на тех же портах.
- Не менять `data/`, `logs/`, `.env` «для проверки» на рабочем инстансе.
- Не удалять БД и не накатывать «с нуля» как штатное решение.
- Не публиковать `8000`/`21116` в интернет без TLS/фильтрации и понимания
  модели доверия (`docs/SECURITY.md`).
- Не добавлять `DEV_MODE=1` в production.
- Не коммитить секреты, `keys/`, `data/`, backup-файлы.
- Не считать, что `logs/app.log` существует.
