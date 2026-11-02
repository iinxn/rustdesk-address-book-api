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
- Автотесты: `pytest` на временной БД, см. `docs/development/TESTING.md`.
- Docker-файлы в git, см. §4. Docker на машине разработки не установлен.
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

Файлы: `Dockerfile`, `docker-compose.yml`, `.dockerignore`,
`scripts/docker-entrypoint.sh` — все в git, секретов не содержат. Настройки,
зависящие от установки (секреты, БД, сессии, прокси, шим, аудит, уровень
логов), перечислены со значениями по умолчанию и комментариями прямо в
`docker-compose.yml` (`environment:`); их правят там и применяют
`docker compose up -d`. Лимиты, ёмкость шима, пул bcrypt и внутренние
параметры аудита оставлены на дефолтах кода; при необходимости любую
переменную из таблицы `README.md` «Configuration» можно добавить строкой в
`environment:`. Контейнерные `HOST`/`PORT`/`SHIM_LISTEN`/`SHIM_ID_KEY` заданы в
образе и не меняются. Секреты подставляются из `.env` рядом с compose
(`${DEVICE_SECRET:-}`), а если их нет — генерируются entrypoint'ом.

### 4.1. Образ

- Stage 1 (`node:22-slim`, всегда на платформе сборщика) собирает SPA;
  stage 2 — `python:3.13-slim`, ставит только `requirements.txt`
  (dev/audit-инструменты — в `requirements-dev.txt`).
- `.dockerignore` — allow-list: в контекст сборки попадают только `app/`,
  `alembic/`, `alembic.ini`, `requirements.txt`, `frontend/` (без
  `node_modules`/`dist`) и entrypoint. `.env`, `data/`, `keys/`, `*.db`,
  `.git` в образ и даже в контекст не попадают.
- Код принадлежит root и только читается; процесс работает как `appuser`
  UID/GID 1000 и пишет только в `/app/data` (volume). Байткод собран при
  сборке.
- В образе заданы контейнерные значения `HOST=0.0.0.0`, `PORT=8000`,
  `SHIM_LISTEN=0.0.0.0:21116`, `SHIM_ID_KEY=/app/keys/id_ed25519`.
- `HEALTHCHECK` опрашивает `/health/ready` на `$PORT`.
- Entrypoint: проверяет, что `/app/data` доступен на запись (иначе понятная
  ошибка и выход), выставляет `umask 077`, генерирует `DEVICE_SECRET`/
  `WEB_SECRET`, если они пустые или `CHANGEME*`, и сохраняет их в
  `/app/data/.secrets.env` (600, атомарная запись). Явно заданные значения
  всегда выигрывают; значения не печатаются. Если файл секретов записать
  нельзя — контейнер **не стартует**: временные секреты потеряли бы пароли
  устройств при следующем рестарте.

### 4.2. Запуск через compose

```bash
mkdir -p data keys
# только если SHIM_ENABLED=1 (файл обязательно называется id_ed25519):
cp /path/to/hbbs-id_ed25519 keys/id_ed25519 && chmod 600 keys/id_ed25519
# правка настроек: docker-compose.yml, раздел environment

docker compose up -d --build    # с Docker Hub: image: <user>/...; docker compose pull
docker compose logs -f app      # ждать "migrations ok"
curl -s http://127.0.0.1:8000/health/ready
docker compose exec app python -m app.cli create-admin
```

Что происходит при `docker compose up -d`:

1. Compose читает `docker-compose.yml`; `${DEVICE_SECRET:-}` и
   `${WEB_SECRET:-}` подставляются из окружения shell или из `.env` в том же
   каталоге (больше compose из `.env` ничего не берёт).
2. Если образа `image:` нет локально — собирает его по `build: .`
   (или берёт с Docker Hub после `docker compose pull`).
3. Создаёт сеть и контейнер: монтирует `./data` → `/app/data` и
   `./keys` → `/app/keys:ro`, публикует порты, передаёт `environment:`.
4. В контейнере стартует `docker-entrypoint.sh`: проверка записи в
   `/app/data`, секреты (из env → из `data/.secrets.env` → генерация).
5. `exec python -m app`: проверка конфигурации, `alembic upgrade head`,
   `migrations ok`, uvicorn на `HOST:PORT`, шим (если `SHIM_ENABLED=1`),
   фоновые задачи discovery и retention.
6. Через ~30 с `HEALTHCHECK` начинает опрашивать `/health/ready`;
   статус виден в `docker compose ps` (`healthy`).

Что ещё задаёт `docker-compose.yml`:

- Порты: `8000:8000` и `21116:21116` **TCP и UDP** (клиент использует оба).
  За прокси на том же хосте — `"127.0.0.1:8000:8000"`; клиенту с пустым
  `api-server` нужен `"21114:8000"` (ERR-009). Меняется только сторона хоста.
- `extra_hosts: host.docker.internal:host-gateway` — для hbbs на том же
  хосте (`SHIM_UPSTREAM=host.docker.internal:21166`). `127.0.0.1` внутри
  контейнера — это сам контейнер, а не хост.
- Hardening: `read_only: true` + `tmpfs /tmp`, `cap_drop: [ALL]`,
  `no-new-privileges`; ротация json-логов 10 МБ × 5; `stop_grace_period: 30s`.

Особенности:

- Значения в `environment:` — в кавычках; литерал `$` пишется как `$$`.
  Если секреты вписаны прямо в compose — `chmod 600` и не коммитить.
- Образ работает как UID 1000. Если `./data` принадлежит другому
  пользователю — `user: "UID:GID"` в compose или `chown` каталога. Ключ в
  `keys/` тоже должен читаться этим UID.
- `DATABASE_URL` с относительным именем (`sqlite:///pc-service.db`)
  привязывается к `data/` и одинаково работает нативно и в контейнере.
  Абсолютный путь хоста в контейнере не существует. Пусто — `base.db`.
- **Не запускай нативный процесс и контейнер на одном `data/` одновременно**:
  два процесса на одной SQLite-базе и на одних портах.
- `TRUSTED_PROXIES`: прокси на хосте ходит в опубликованный порт через
  docker-proxy, и приложение видит адрес шлюза docker-сети (например
  `172.18.0.1`, см. `docker network inspect`), а не `127.0.0.1`. Внешние
  клиенты на опубликованных портах приходят со своими адресами.
- Без compose: `docker run --env-file <файл>` не обрезает комментарии в
  строке со значением — пиши комментарии отдельной строкой.
- Логи: `docker compose logs -f app`; файла `logs/app.log` нет.
- Остановка: `docker compose down` (данные на хосте остаются).

### 4.3. Перенос нативной установки в контейнер

1. Останови нативный процесс (`./scripts/stop.sh`) и сделай
   `.venv/bin/python -m app.cli backup`.
2. Секреты: нативный `.env` в каталоге с compose подставит прежние
   `DEVICE_SECRET`/`WEB_SECRET` автоматически. Другой `DEVICE_SECRET` =
   нечитаемые пароли устройств.
3. Перенеси нужные настройки из `.env` в `environment:` compose;
   `DATABASE_URL` — пусто или относительное имя (см. выше).
4. `docker compose up -d --build`; убедись, что в панели прежние книги.

### 4.4. Обновление

```bash
docker compose exec app python -m app.cli backup   # или копия data/ при остановленном контейнере
docker compose pull   # для готового образа; для локального — up --build
docker compose up -d
docker compose logs -f app   # миграции применяются при старте
```

### 4.5. Публикация на Docker Hub

```bash
docker login
docker buildx create --use --name multi   # один раз
docker buildx build --platform linux/amd64,linux/arm64 \
  --build-arg VERSION=1.0.0 --build-arg REVISION="$(git rev-parse --short HEAD)" \
  -t <user>/rustdesk-ab-backend:1.0.0 -t <user>/rustdesk-ab-backend:latest \
  --push .
```

Собирай из чистого клона или проверь `git status`: образ берёт файлы из
рабочего каталога, включая незакоммиченные (ERR-005). На сервере достаточно
`docker-compose.yml` с `image: <user>/rustdesk-ab-backend:1.0.0` (и при
желании `.env` с секретами); `build: .` при наличии образа не используется. Проверка содержимого образа:
`docker run --rm --entrypoint ls <image> /app/alembic/versions`.

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
# backup SQLite (integrity_check + mode 600). БД в режиме WAL: рядом лежат
# <db>-wal и <db>-shm; копировать один файл БД при работающем процессе нельзя,
# только через эту команду (SQLite Backup API).
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
