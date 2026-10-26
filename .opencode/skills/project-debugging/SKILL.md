---
name: project-debugging
description: >
  Use when diagnosing this project's runtime problems: RustDesk client cannot
  connect, `Failed to secure tcp`, shim crash-loop or `down` in
  `/health/ready`, discovery shows wrong/stuck presence, sysinfo is missing,
  Docker container restarts, or the API misbehaves. Routes the symptom to the
  right layer (HTTP API, TCP KX, UDP, upstream hbbs, SQLite) and to the
  canonical docs instead of guessing.
---

# Project debugging

Цель — за минимум шагов отделить слой, в котором произошла ошибка, и не
«лечить» симптом таймаутом или перезапуском. Источник истины — код и
фактические логи, не догадки.

## 1. Сначала прочитай

- `docs/knowledge/ERRORS.md` — найди точный текст ошибки.
- `docs/development/WORKFLOW.md` §8 — диагностика, порты, типовые причины.
- `docs/project/ARCHITECTURE.md` §6–9 — shim, discovery, sysinfo.
- `docs/SECURITY.md` §3 — что вообще опубликовано наружу.

## 2. Раздели слои

| Симптом | Слой | Первая проверка |
|---|---|---|
| `Failed to secure tcp: deadline has elapsed` | TCP KX | `ss -tlnp \| grep 21116`, `/health/ready`, `secure established` в логах |
| shim падает/рестартит | процесс shim | текст ошибки: bind IP, длина ключа, занятый порт |
| соединение идёт, но не работает | upstream/relay | `SHIM_UPSTREAM` — rendezvous, не `21117` |
| discovery «завис» / неверный online | очередь + sweep | `DISCOVERY_ENABLED`, логи drain, `DISCOVERY_ONLINE_SEC` |
| нет sysinfo | HTTP API клиента | пустой `api-server` → клиент идёт на `21114`; API должен слушать/быть опубликован на этом порту |
| пустая панель в Docker | SQLite | `DATABASE_URL` указывает на тот ли файл, volume подключён |
| контейнер в рестарте | миграции | `Can't locate revision` → файла миграции нет в образе/git |

## 3. Собери факты (без секретов)

```bash
curl -si http://127.0.0.1:8000/health/ready
ss -tlnp | grep -E ':8000|:21114|:21116'
ss -ulnp | grep 21116
ps -eo pid,user,cmd | grep -E 'python -m app' | grep -v grep
```

Для shim смотри в логах `secure established`, `plain passthrough`,
`shim exited`, текст причины падения. Ключи/токены не печатай; допустимы
только отпечатки (`scripts/check_keys.py`).

## 4. Правила

- Не увеличивай timeout/retry, пока причина не установлена.
- Не меняй рабочую БД и `.env` «для проверки». Разрушительные сценарии —
  только на временной БД/порту (`docs/development/TESTING.md` §3).
- Не запускай второй экземпляр на тех же портах.
- Не смешивай heartbeat, discovery и sysinfo: это разные источники.
- После фикса проверь `/health/ready`, логин, `/api/ab/personal` и нужный
  сценарий; запиши, что именно проверено.

## 5. Если это новая ошибка

Добавь подтверждённый инцидент в `docs/knowledge/ERRORS.md` по формату
«симптом → причина → что делать → как не повторить». Не выдумывай причину,
если она не доказана; пометь «требует проверки».
